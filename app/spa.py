"""Serve the Vite production build (``app/static/``) with an SPA fallback.

Registered after all API routes (see ``main.py``), so the catch-all only
receives paths no API route claimed — API GETs win, everything else returns
``index.html`` for client-side routing.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_ROOT = Path(__file__).resolve().parent / "static"
INDEX_HTML = STATIC_ROOT / "index.html"


def register_spa(app: FastAPI) -> bool:
    """Mount built frontend assets + SPA fallback. False if no build present."""
    if not INDEX_HTML.is_file():
        return False

    assets_dir = STATIC_ROOT / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        # Serve a real built file (favicon, vite.svg, …) when it exists;
        # otherwise hand back index.html for client-side routing.
        candidate = STATIC_ROOT / full_path
        if (
            full_path
            and candidate.is_file()
            and candidate.resolve().is_relative_to(STATIC_ROOT)
        ):
            return FileResponse(candidate)
        return FileResponse(INDEX_HTML)

    return True
