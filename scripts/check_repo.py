"""Repository hygiene checks, run locally and in CI: `python scripts/check_repo.py`.

Checks (exit code 1 when any fails):
  secrets   anchored API key patterns in tracked files (sk-, gsk_, hf_, lsv2_, private keys)
  manifest  gigsim/ files match gigsim/MANIFEST.sha256 (the simulator must not be modified)
  prompts   no long inline prompt string literal in agent/**/*.py (prompts live in agent/prompts)
  results   every number inside README / report marker blocks exists in some evals/results file
  env       .env is not tracked

Regenerate the manifest only for a legitimate gigsim change: python scripts/check_repo.py --write-manifest
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "gigsim" / "MANIFEST.sha256"
RESULTS_DIR = ROOT / "evals" / "results"
MARKER_FILES = ["README.md", "docs/report/REPORT.md", "docs/results_tables.md"]
START, END = "[//]: # (results:start)", "[//]: # (results:end)"
PROMPT_MIN_LEN = 200

# Anchored with a word boundary so that "risk-based" never matches the sk- pattern.
SECRET_PATTERNS = {
    "openai style key": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "groq key": re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),
    "huggingface token": re.compile(r"\bhf_[A-Za-z0-9]{20,}"),
    "langsmith key": re.compile(r"\blsv2_[A-Za-z0-9_]{20,}"),
    "private key": re.compile(r"-{5}BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-{5}"),
}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".npy", ".ico", ".woff", ".woff2",
               ".pyc", ".sqlite"}
SKIP_NAMES = {"package-lock.json", "MANIFEST.sha256"}


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.splitlines()
        files = [ROOT / p for p in out if p]
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in ROOT.rglob("*") if p.is_file()
                 and not {".git", ".venv", "node_modules", ".next", "__pycache__"} & set(p.parts)]
    return [p for p in files if p.is_file()]


def read_text(p: Path) -> str | None:
    if p.suffix.lower() in SKIP_SUFFIX or p.name in SKIP_NAMES:
        return None
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def check_secrets(files: list[Path]) -> list[str]:
    errors = []
    for p in files:
        text = read_text(p)
        if text is None:
            continue
        for label, pat in SECRET_PATTERNS.items():
            if pat.search(text):
                errors.append(f"{p.relative_to(ROOT).as_posix()}: looks like a {label}")
    return errors


def check_env_not_tracked(files: list[Path]) -> list[str]:
    return [f"{p.relative_to(ROOT).as_posix()} must not be tracked" for p in files
            if p.name == ".env" or p.name.startswith(".env.") and p.name != ".env.example"]


# == gigsim manifest ==

def _digest(p: Path) -> str:
    data = p.read_bytes().replace(b"\r\n", b"\n")  # same hash on Windows and Linux checkouts
    return hashlib.sha256(data).hexdigest()


def gigsim_files() -> list[Path]:
    return sorted(p for p in (ROOT / "gigsim").rglob("*")
                  if p.is_file() and p.name != "MANIFEST.sha256" and "__pycache__" not in p.parts
                  and p.suffix != ".pyc")


def build_manifest() -> str:
    return "".join(f"{_digest(p)}  {p.relative_to(ROOT).as_posix()}\n" for p in gigsim_files())


def check_manifest() -> list[str]:
    if not MANIFEST.exists():
        return ["gigsim/MANIFEST.sha256 is missing (run with --write-manifest once)"]
    expected = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, _, name = line.partition("  ")
            expected[name.strip()] = digest.strip()
    actual = {p.relative_to(ROOT).as_posix(): _digest(p) for p in gigsim_files()}
    errors = [f"{n}: changed (gigsim must not be modified)" for n in actual
              if n in expected and actual[n] != expected[n]]
    errors += [f"{n}: new file not in manifest" for n in actual if n not in expected]
    errors += [f"{n}: listed in manifest but missing" for n in expected if n not in actual]
    return errors


# == inline prompts ==

def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def check_inline_prompts() -> list[str]:
    errors = []
    for p in sorted((ROOT / "agent").rglob("*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            errors.append(f"{p.relative_to(ROOT).as_posix()}: cannot parse ({exc})")
            continue
        docs = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docs and len(node.value) > PROMPT_MIN_LEN
                    and "You " in node.value):
                errors.append(f"{p.relative_to(ROOT).as_posix()}:{node.lineno}: inline prompt "
                              f"({len(node.value)} chars), move it to agent/prompts/")
    return errors


# == numbers in marker blocks ==

NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?%?(?![\w])")


def _json_numbers(obj, out: list[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, int | float):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _json_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _json_numbers(v, out)


def result_numbers() -> tuple[list[float], str]:
    nums: list[float] = []
    text = ""
    for p in sorted(RESULTS_DIR.rglob("*")) if RESULTS_DIR.exists() else []:
        if not p.is_file():
            continue
        raw = p.read_text(encoding="utf-8", errors="ignore")
        text += raw + "\n"
        if p.suffix == ".json":
            try:
                _json_numbers(json.loads(raw), nums)
            except json.JSONDecodeError:
                pass
    return nums, text


def _matches(token: str, nums: list[float], text: str) -> bool:
    if token in text:
        return True
    pct = token.endswith("%")
    body = token.rstrip("%")
    try:
        x = float(body)
    except ValueError:
        return True
    decimals = len(body.split(".")[1]) if "." in body else 0
    for v in nums:
        cand = v * 100 if pct else v
        if round(cand, decimals) == x or abs(cand - x) < 1e-9:
            return True
        if not pct and decimals == 0 and round(v) == x:
            return True
    return False


def marker_blocks(text: str) -> list[str]:
    blocks, pos = [], 0
    while (s := text.find(START, pos)) != -1:
        e = text.find(END, s)
        if e == -1:
            blocks.append(text[s + len(START):])
            break
        blocks.append(text[s + len(START):e])
        pos = e + len(END)
    return blocks


def check_results_numbers() -> list[str]:
    nums, text = result_numbers()
    errors = []
    for rel in MARKER_FILES:
        p = ROOT / rel
        if not p.exists():
            continue
        for block in marker_blocks(p.read_text(encoding="utf-8")):
            for line in block.splitlines():
                if line.lstrip().startswith(("#", "[//]:")) or "not measured" in line.lower():
                    continue
                if line.lower().startswith(("source", "generated")):
                    continue
                for tok in NUM.findall(line):
                    if not _matches(tok, nums, text):
                        errors.append(f"{rel}: number {tok} is not in any evals/results file "
                                      f"(line: {line.strip()[:80]})")
    return errors


def main() -> int:
    if "--write-manifest" in sys.argv:
        MANIFEST.write_text(build_manifest(), encoding="utf-8", newline="\n")
        print(f"wrote {MANIFEST.relative_to(ROOT).as_posix()} ({len(gigsim_files())} files)")
        return 0
    files = tracked_files()
    checks = {
        "secrets": check_secrets(files),
        "env": check_env_not_tracked(files),
        "manifest": check_manifest(),
        "prompts": check_inline_prompts(),
        "results": check_results_numbers(),
    }
    failed = False
    for name, errors in checks.items():
        if errors:
            failed = True
            print(f"FAIL {name}")
            for e in errors:
                print(f"  {e}")
        else:
            print(f"ok   {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
