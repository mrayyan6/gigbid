# ruff: noqa: B008
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from apps.api.auth import get_current_user
from apps.api.schemas import PortfolioItemOut, PortfolioOut, UploadOut, UserOut
from rag.ingest.user_store import MAX_BYTES, add_files, load_user_items
from rag.retriever import get_corpus, user_corpus

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
MAX_FILES = 10


@router.get("", response_model=PortfolioOut, operation_id="get_portfolio")
async def get_portfolio(user: UserOut = Depends(get_current_user)) -> PortfolioOut:
    return PortfolioOut(
        seeded_items=len(get_corpus(user.persona).items),
        uploaded=[PortfolioItemOut(evidence_id=i["evidence_id"], type=i["type"], title=i["title"],
                                   skills=i["skills"], source=i["source"]) for i in load_user_items(user.id)])


@router.post("/upload", response_model=UploadOut, operation_id="upload_portfolio")
async def upload_portfolio(files: list[UploadFile] = File(...),
                           user: UserOut = Depends(get_current_user)) -> UploadOut:
    """Add work to the user's own portfolio and re-index it incrementally: only the new chunks are embedded.
    The uploads are private to this user (tenant scoped) and used as evidence in this user's runs."""
    if not files or len(files) > MAX_FILES:
        raise HTTPException(422, f"send between 1 and {MAX_FILES} files")
    blobs = [(f.filename or "upload", await f.read(MAX_BYTES + 1)) for f in files]
    res = await asyncio.to_thread(add_files, user.id, user.persona, blobs)
    _, stats = await asyncio.to_thread(user_corpus, user.persona, user.id)
    return UploadOut(added=res["added"], duplicates=res["duplicates"], rejected=res["rejected"],
                     chunks_embedded=stats["chunks_embedded"], reindex_seconds=stats["seconds"],
                     user_items=stats["user_items"], seeded_items=len(get_corpus(user.persona).items))
