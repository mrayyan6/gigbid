"""Per user portfolio additions: parse uploaded files into evidence items and keep them per tenant.

Supported files: PDF (CVs), Markdown and plain text (case studies, repo READMEs, reviews, past proposals) and
JSON (one item or a list of items). Every item gets the same metadata as the seeded portfolio: persona, type,
project, skills, date, client industry and outcome. Items are content addressed, so uploading the same file
twice adds nothing. Files live under data/processed/user_portfolio/<user id>.json (git ignored).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
from datetime import date
from pathlib import Path

from rag.config import ROOT
from rag.ingest.load import load_portfolio, with_text

SUPPORTED = {".md", ".markdown", ".txt", ".json", ".pdf"}
MAX_BYTES = 2_000_000
MIN_WORDS = 8
INDUSTRIES = ["logistics", "fintech", "retail", "health", "education", "media", "saas", "insurance", "travel"]


def store_dir() -> Path:
    root = os.environ.get("USER_PORTFOLIO_DIR") or (
        str(Path(os.environ["STATE_DIR"]) / "user_portfolio") if os.environ.get("STATE_DIR")
        else str(ROOT / "data" / "processed" / "user_portfolio"))
    d = Path(root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(user_id: str) -> Path:
    return store_dir() / (re.sub(r"[^A-Za-z0-9_.-]", "_", user_id) + ".json")


def _read(user_id: str) -> list[dict]:
    p = _path(user_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def has_items(user_id: str) -> bool:
    return bool(_read(user_id))


def load_user_items(user_id: str) -> list[dict]:
    """The user's uploaded evidence items, in the same shape (with text) as the seeded portfolio."""
    return [with_text(i) for i in _read(user_id)]


def version(items: list[dict]) -> str:
    return hashlib.sha1("|".join(sorted(i["evidence_id"] for i in items)).encode()).hexdigest()[:12]


def known_skills() -> list[str]:
    """Vocabulary used to tag uploaded text with skills: every skill in any seeded persona portfolio."""
    return sorted({s for i in load_portfolio(None) for s in i["skills"]})


def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages)
    return data.decode("utf-8", errors="replace")


CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".sql", ".ipynb"}


def _kind(name: str) -> str:
    low = name.lower()
    if Path(low).suffix in CODE_EXT:
        return "code"
    if re.search(r"(^|[^a-z])(cv|resume)([^a-z]|$)", low):
        return "cv"
    if "readme" in low:
        return "readme"
    if "review" in low:
        return "review"
    if "proposal" in low:
        return "past_proposal"
    return "case_study"


def make_item(user_id: str, persona: str, filename: str, text: str, skills_vocab: list[str],
              source: str = "user_upload") -> dict | None:
    raw = text.strip()
    heading = re.search(r"^\s*#\s+(.+)$", raw, re.MULTILINE)
    flat = re.sub(r"\s+", " ", re.sub(r"^\s*#+\s*", "", raw, flags=re.MULTILINE)).strip()
    if len(flat.split()) < MIN_WORDS:
        return None
    title = (heading.group(1).strip() if heading else Path(filename).stem.replace("_", " ").replace("-", " ").title())
    skills = [s for s in skills_vocab if re.search(rf"(?<![A-Za-z0-9]){re.escape(s)}(?![A-Za-z0-9])", flat, re.IGNORECASE)]
    outcome = next((s.strip() for s in re.split(r"(?<=[.!?])\s+", flat)
                    if re.search(r"\d+\s?%|\breduc|\bincreas|\bcut\b|\bimprov|\bsaved\b|\bfrom \d", s, re.IGNORECASE)), "")
    industry = next((i for i in INDUSTRIES if re.search(rf"\b{i}\b", flat, re.IGNORECASE)), "unknown")
    summary = " ".join(flat.split()[:120])
    return {"evidence_id": "u-" + hashlib.sha1(f"{user_id}|{flat}".encode()).hexdigest()[:12],
            "freelancer_id": persona, "type": _kind(filename), "title": title[:120],
            "project": title.lower()[:120], "skills": skills, "date": date.today().isoformat(),
            "client_industry": industry, "summary": summary, "outcome": outcome[:240],
            "source": source, "filename": filename}


def add_files(user_id: str, persona: str, files: list[tuple[str, bytes]]) -> dict:
    """Parse and store uploaded files. Returns counts; nothing is stored for rejected files."""
    vocab = known_skills()
    existing = _read(user_id)
    ids = {i["evidence_id"] for i in existing}
    added, dup, rejected = [], 0, []
    for name, data in files:
        ext = Path(name).suffix.lower()
        if ext not in SUPPORTED:
            rejected.append(f"{name}: unsupported type (use PDF, Markdown, text or JSON)")
            continue
        if len(data) > MAX_BYTES:
            rejected.append(f"{name}: larger than {MAX_BYTES // 1_000_000} MB")
            continue
        try:
            if ext == ".json":
                obj = json.loads(data.decode("utf-8"))
                texts = [(f"{name}:{n}", " ".join(str(v) for v in (o.values() if isinstance(o, dict) else [o])))
                         for n, o in enumerate(obj if isinstance(obj, list) else [obj])]
            else:
                texts = [(name, extract_text(name, data))]
        except Exception as exc:
            rejected.append(f"{name}: could not be read ({type(exc).__name__})")
            continue
        for label, text in texts:
            item = make_item(user_id, persona, name if ext != ".json" else label, text, vocab)
            if item is None:
                rejected.append(f"{name}: too little text to index")
            elif item["evidence_id"] in ids:
                dup += 1
            else:
                ids.add(item["evidence_id"])
                added.append(item)
    if added:
        _path(user_id).write_text(json.dumps(existing + added, indent=1), encoding="utf-8")
    return {"added": len(added), "duplicates": dup, "rejected": rejected}


def add_texts(user_id: str, persona: str, texts: list[tuple[str, str]], source: str = "github_mcp") -> dict:
    """Store text that was fetched rather than uploaded, for example a README read through the GitHub MCP server."""
    vocab = known_skills()
    existing = _read(user_id)
    ids = {i["evidence_id"] for i in existing}
    added, dup, rejected = [], 0, []
    for name, text in texts:
        item = make_item(user_id, persona, name, text, vocab, source=source)
        if item is None:
            rejected.append(f"{name}: too little text to index")
        elif item["evidence_id"] in ids:
            dup += 1
        else:
            ids.add(item["evidence_id"])
            added.append(item)
    if added:
        _path(user_id).write_text(json.dumps(existing + added, indent=1), encoding="utf-8")
    return {"added": len(added), "duplicates": dup, "rejected": rejected}
