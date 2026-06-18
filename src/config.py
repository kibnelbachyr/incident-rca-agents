# Copyright (c) Microsoft. All rights reserved.

"""Centralized demo configuration (read from the environment / .env).

All the "non-negotiable" constants (confidence threshold, reflection loop
bound, knowledge base mode, ...) live here to avoid them being scattered or
hardcoded across the agents/graph.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Orchestration and connection settings, loaded from `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Azure OpenAI / Microsoft Foundry ---
    azure_openai_endpoint: str | None = Field(default=None, alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_chat_deployment: str = Field(default="gpt-4o", alias="AZURE_OPENAI_CHAT_DEPLOYMENT")
    azure_openai_chat_deployment_light: str = Field(
        default="gpt-4o-mini", alias="AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT"
    )
    azure_openai_api_version: str = Field(default="2024-10-21", alias="AZURE_OPENAI_API_VERSION")

    # "cli" -> AzureCliCredential (local dev, `az login`)
    # "managed_identity" -> DefaultAzureCredential (deployed on Azure)
    azure_auth_mode: Literal["cli", "managed_identity"] = Field(default="cli", alias="AZURE_AUTH_MODE")

    # Microsoft Foundry project endpoint (form "https://<account>.services.ai.azure.com/api/projects/<project>"),
    # provisioned by `infra/resources.bicep` (output AZURE_FOUNDRY_PROJECT_ENDPOINT).
    # Used only by scripts/register_foundry_agents.py (docs/deployment.md #8.13);
    # unrelated to agent execution, which always goes through AZURE_OPENAI_ENDPOINT.
    azure_foundry_project_endpoint: str | None = Field(default=None, alias="AZURE_FOUNDRY_PROJECT_ENDPOINT")

    # --- Azure AI Search (RAG knowledge base, deployed mode) ---
    azure_ai_search_endpoint: str | None = Field(default=None, alias="AZURE_AI_SEARCH_ENDPOINT")
    azure_ai_search_index: str = Field(default="incident-kb", alias="AZURE_AI_SEARCH_INDEX")

    # --- Azure Cosmos DB (persistence, optional for the demo) ---
    cosmos_endpoint: str | None = Field(default=None, alias="COSMOS_ENDPOINT")
    cosmos_database: str = Field(default="incidents", alias="COSMOS_DATABASE")
    cosmos_container: str = Field(default="records", alias="COSMOS_CONTAINER")

    # --- Observability ---
    applicationinsights_connection_string: str | None = Field(
        default=None, alias="APPLICATIONINSIGHTS_CONNECTION_STRING"
    )
    enable_sensitive_data: bool = Field(default=False, alias="ENABLE_SENSITIVE_DATA")

    # --- Orchestration settings (non-negotiable constraints) ---
    confidence_threshold: float = Field(default=0.75, alias="CONFIDENCE_THRESHOLD")
    max_reflection_loops: int = Field(default=2, alias="MAX_REFLECTION_LOOPS")
    kb_mode: Literal["local", "azure_search"] = Field(default="local", alias="KB_MODE")

    # --- Local paths (KB_MODE=local mode) ---
    knowledge_base_path: Path = Field(default=REPO_ROOT / "data" / "knowledge_base.json")

    @property
    def use_real_azure_openai(self) -> bool:
        """True if a usable Azure OpenAI endpoint is configured.

        Used to automatically switch between the real Azure OpenAI client
        (Microsoft Agent Framework) and the deterministic "stub" client used
        offline for the demo.
        """
        endpoint = self.azure_openai_endpoint
        if not endpoint:
            return False
        return not endpoint.startswith("https://<")


def get_settings() -> Settings:
    """Loads settings from the environment / `.env`."""

    return Settings()
