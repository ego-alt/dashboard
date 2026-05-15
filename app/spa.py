"""Serve the Vite production build (``app/static/``) with SPA fallbacks."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_ROOT = Path(__file__).resolve().parent / "static"
INDEX_HTML = STATIC_ROOT / "index.html"


def register_spa(app: FastAPI) -> bool:
    """Mount built frontend assets. Returns True when index.html is present."""
    if not INDEX_HTML.is_file():
        return False

    assets_dir = STATIC_ROOT / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    def serve_index():
        return FileResponse(INDEX_HTML)

    for path in ("/", "/login", "/monitor"):
        app.get(path, include_in_schema=False)(serve_index)

    return True
