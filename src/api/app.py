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

# configure_azure_monitor() must run before FastAPI() is instantiated so that
# opentelemetry-instrumentation-fastapi patches the class in time. Import
# observability first, call configure, then import FastAPI. (Azure Monitor
# OpenTelemetry distro Python troubleshooting guide)
from src.config import REPO_ROOT, get_settings
from src.observability import configure_observability

configure_observability(get_settings())

from fastapi import FastAPI  # noqa: E402 — must follow configure_observability()
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api import history, meta, runs

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
