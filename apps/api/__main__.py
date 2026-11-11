"""Dev launcher: python -m apps.api

On Windows, psycopg (Postgres checkpointer) needs the selector event loop, which a plain
`uvicorn apps.api.main:app` does not select. On Linux (Docker, Spaces) use uvicorn directly.
"""
import asyncio
import os
import sys

import uvicorn

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run("apps.api.main:app", host=os.environ.get("API_HOST", "127.0.0.1"),
                port=int(os.environ.get("API_PORT", "8000")), loop="asyncio")
