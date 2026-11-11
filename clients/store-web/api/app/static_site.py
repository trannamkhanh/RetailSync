"""Serve the built SPA from ``web/dist`` next to the JSON API.

One process, one port: after ``pnpm build`` the API answers ``/api/*`` with JSON
and every other path with the SPA shell, so a refresh at a client route works
and ``/api/unknown`` still gets a JSON 404 instead of ``index.html``.
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.errors import ApiError

logger = logging.getLogger(__name__)

DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


class _HashedAssets(StaticFiles):
    """Vite asset names carry a content hash, so they can be cached forever."""

    def file_response(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount_spa(app: FastAPI) -> None:
    """Mount ``web/dist`` and the SPA fallback, or warn when it was not built."""
    dist = DIST
    if not (dist / "index.html").is_file():
        logger.warning(
            "web/dist is missing; run `pnpm build` in clients/store-web/web. "
            "GET / will return 404 until then."
        )
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", _HashedAssets(directory=assets), name="assets")

    dist_resolved = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise ApiError(404, "NOT_FOUND", f"No API route for /{full_path}.")

        if full_path:
            target = (dist / full_path).resolve()
            if target.is_file() and dist_resolved in target.parents:
                return FileResponse(
                    target,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"},
                )
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
