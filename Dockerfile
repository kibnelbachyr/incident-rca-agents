# Copyright (c) Microsoft. All rights reserved.

# Image de demo pour le CLI d'orchestration (src/main.py, SPEC.md section 7).
#
# Conformement a CLAUDE.md : aucune action corrective n'est executee, la
# remediation reste un plan affiche derriere une validation humaine ; aucun
# secret n'est integre a l'image (configuration via variables d'environnement
# / Key Vault, voir .env.example et README.md).

FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY data ./data

# Installation "editable" : src.config.REPO_ROOT (utilise pour les chemins par
# defaut data/payment-incident.log et data/knowledge_base.json) reste aligne
# sur /app, sans avoir a dupliquer data/ dans site-packages.
RUN pip install --no-cache-dir -e .

RUN useradd --create-home --uid 1000 demo
USER demo

# "managed_identity" -> DefaultAzureCredential, attendu en deploiement
# (Container Apps + identite managee). En local hors-ligne (StubChatClient),
# ni AZURE_OPENAI_ENDPOINT ni credential ne sont requis (DECISIONS.md #3).
ENV AZURE_AUTH_MODE=managed_identity

ENTRYPOINT ["python", "-m", "src.main"]
