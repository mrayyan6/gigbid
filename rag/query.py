"""Query side helpers: requirement decomposition (V1) and the rewrite used by the corrective loop (V8)."""
from __future__ import annotations

import re

from rag.config import cfg


def decompose(text: str, use_marker: bool = True) -> list[str]:
    """Split a job text into requirement phrases. Rule based, deterministic, no LLM call.

    1. use_marker and the text has a 'Required: a, b, c.' marker: those items are the requirements.
       (In the synthetic data this marker lists exactly the gold skills, see the circularity note.)
    2. Else, without the marker: short text is one requirement; long text is split on sentences and commas.
    3. use_marker=False is the robustness mode: always split on sentences, commas and 'and',
       dropping boilerplate such as a leading 'Required:'. No oracle list is read.
    """
    c = cfg()["decompose"]
    if use_marker:
        m = re.search(c["marker_regex"], text)
        if m:
            parts = [p.strip() for p in re.split(r",|;|\band\b", m.group(1)) if p.strip()]
            if parts:
                return [c["requirement_template"].format(req=p) for p in parts]
        if len(text.split()) < c["min_words_without_marker"]:
            return [text]
        parts = [p.strip() for p in re.split(r"[.;,]|\band\b", text) if len(p.split()) >= 2]
        return parts or [text]
    parts = [re.sub(r"(?i)^required\s*:\s*", "", p.strip()).strip() for p in re.split(r"[;,]|\.(?!\w)|\band\b", text)]
    parts = [p for p in parts if p]
    return parts or [text]


def requirement_name(req: str) -> str:
    """Inverse of the template, used to look up related skills."""
    tpl = cfg()["decompose"]["requirement_template"]
    pre = tpl.split("{req}")[0]
    return req[len(pre):] if req.startswith(pre) else req
