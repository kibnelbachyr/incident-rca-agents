# Copyright (c) Microsoft. All rights reserved.

"""Configuration centralisee de la demo (lue depuis l'environnement / .env).

Toutes les constantes "non negociables" (seuil de confiance, borne de la
boucle de reflexion, mode de la base de connaissances, ...) vivent ici pour
eviter qu'elles soient eparpillees ou codees en dur dans les agents/le graphe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Parametres d'orchestration et de connexion, charges depuis `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Azure OpenAI / Microsoft Foundry ---
    azure_openai_endpoint: str | None = Field(default=None, alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_chat_deployment: str = Field(default="gpt-4o", alias="AZURE_OPENAI_CHAT_DEPLOYMENT")
    azure_openai_chat_deployment_light: str = Field(
        default="gpt-4o-mini", alias="AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT"
    )
    azure_openai_api_version: str = Field(default="2024-10-21", alias="AZURE_OPENAI_API_VERSION")

    # "cli" -> AzureCliCredential (dev local, `az login`)
    # "managed_identity" -> DefaultAzureCredential (deploye sur Azure)
    azure_auth_mode: Literal["cli", "managed_identity"] = Field(default="cli", alias="AZURE_AUTH_MODE")

    # --- Azure AI Search (base de connaissances RAG, mode deploye) ---
    azure_ai_search_endpoint: str | None = Field(default=None, alias="AZURE_AI_SEARCH_ENDPOINT")
    azure_ai_search_index: str = Field(default="incident-kb", alias="AZURE_AI_SEARCH_INDEX")

    # --- Azure Cosmos DB (persistance, optionnel pour la demo) ---
    cosmos_endpoint: str | None = Field(default=None, alias="COSMOS_ENDPOINT")
    cosmos_database: str = Field(default="incidents", alias="COSMOS_DATABASE")
    cosmos_container: str = Field(default="records", alias="COSMOS_CONTAINER")

    # --- Observabilite ---
    applicationinsights_connection_string: str | None = Field(
        default=None, alias="APPLICATIONINSIGHTS_CONNECTION_STRING"
    )
    enable_sensitive_data: bool = Field(default=False, alias="ENABLE_SENSITIVE_DATA")

    # --- Parametres d'orchestration (contraintes non negociables) ---
    confidence_threshold: float = Field(default=0.75, alias="CONFIDENCE_THRESHOLD")
    max_reflection_loops: int = Field(default=2, alias="MAX_REFLECTION_LOOPS")
    kb_mode: Literal["local", "azure_search"] = Field(default="local", alias="KB_MODE")

    # --- Chemins locaux (mode KB_MODE=local) ---
    knowledge_base_path: Path = Field(default=REPO_ROOT / "data" / "knowledge_base.json")

    @property
    def use_real_azure_openai(self) -> bool:
        """True si un endpoint Azure OpenAI exploitable est configure.

        Sert a basculer automatiquement entre le client Azure OpenAI reel
        (Microsoft Agent Framework) et le client "stub" deterministe utilise
        hors-ligne pour la demo.
        """
        endpoint = self.azure_openai_endpoint
        if not endpoint:
            return False
        return not endpoint.startswith("https://<")


def get_settings() -> Settings:
    """Charge les parametres depuis l'environnement / `.env`."""

    return Settings()
