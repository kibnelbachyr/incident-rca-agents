# Copyright (c) Microsoft. All rights reserved.

# Image de demo : API d'orchestration (FastAPI, src/api/app.py) + UI (React/Vite,
# frontend/), construites en deux etapes et servies par un seul process uvicorn.
#
# Conformement a CLAUDE.md : aucune action corrective n'est executee, la
# remediation reste un plan affiche derriere une validation humaine ; aucun
# secret n'est integre a l'image (configuration via variables d'environnement
# / Key Vault, voir .env.example et README.md).

# --- Etape 1 : build du frontend (Vite/React) --------------------------------

FROM node:20-slim AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# --- Etape 2 : runtime Python (API + UI statique) ----------------------------

FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY data ./data

# Installation "editable" : src.config.REPO_ROOT (utilise pour les chemins par
# defaut data/payment-incident.log, data/knowledge_base.json et
# frontend/dist/) reste aligne sur /app, sans avoir a dupliquer data/ dans
# site-packages.
RUN pip install --no-cache-dir -e .

# UI buildee (servie par src/api/app.py via StaticFiles si le dossier existe).
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN useradd --create-home --uid 1000 demo
USER demo

# "managed_identity" -> DefaultAzureCredential, attendu en deploiement
# (Container Apps + identite managee). En local hors-ligne (StubChatClient),
# ni AZURE_OPENAI_ENDPOINT ni credential ne sont requis (DECISIONS.md #3).
ENV AZURE_AUTH_MODE=managed_identity

EXPOSE 8000

ENTRYPOINT ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
