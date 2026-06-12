# Copyright (c) Microsoft. All rights reserved.

"""Application FastAPI : expose `build_workflow` (SPEC.md section 5) sur HTTP.

Sert deux roles :

- API JSON/SSE sous `/api/*` (`src/api/runs.py`, `history.py`, `meta.py`),
  consommee par le frontend React (`frontend/`).
- En production (image Docker, `infra/`), sert aussi le build statique du
  frontend (`frontend/dist/`) si present, pour n'exposer qu'un seul service
  Container Apps.

Lancement local : `uvicorn src.api.app:app --reload` (cf. README.md). Les
origines CORS par defaut couvrent le serveur de dev Vite
(`npm run dev`, port 5173) ; en production le frontend est servi en
same-origin et CORS n'est pas necessaire.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api import history, meta, runs
from src.config import REPO_ROOT

DEV_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def create_app() -> FastAPI:
    app = FastAPI(title="Incident RCA Agents API")
    app.state.runs = {}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(runs.router, prefix="/api")
    app.include_router(history.router, prefix="/api")
    app.include_router(meta.router, prefix="/api")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    frontend_dist = REPO_ROOT / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
