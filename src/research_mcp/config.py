"""Configuration system: Pydantic Settings + YAML file + environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GroupsConfig(BaseModel):
    web_search: bool = True
    academic: bool = True
    video: bool = True
    github_docs: bool = True
    document: bool = False
    wikipedia: bool = True
    vector_index: bool = False


class ServicesConfig(BaseModel):
    searxng_url: str = "http://localhost:8080"
    docling_url: str = "http://localhost:5001"
    ollama_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text"


class ScrapingConfig(BaseModel):
    default_tier: str = "basic"
    auto_escalate: bool = True
    timeout_seconds: int = 30
    max_content_length: int = 50000


class AcademicConfig(BaseModel):
    default_sources: list[str] = Field(
        default=["semantic_scholar", "arxiv", "crossref", "openalex"]
    )
    max_results_per_source: int = 10


class CacheTTLConfig(BaseModel):
    search_results: int = 1800
    web_pages: int = 3600
    academic: int = 86400
    transcripts: int = 604800
    embeddings: int = 2592000


class CacheConfig(BaseModel):
    enabled: bool = True
    db_path: str = "~/.research-mcp/cache.db"
    ttl: CacheTTLConfig = CacheTTLConfig()


class VectorIndexConfig(BaseModel):
    db_path: str = "~/.research-mcp/index.db"
    embedding_dimensions: int = 768
    default_top_k: int = 10


class DomainFilterConfig(BaseModel):
    blocklist: list[str] = []
    allowlist: list[str] = []


class ResearchMCPConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RESEARCH_MCP_",
        env_nested_delimiter="__",
    )

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        # Env vars take priority over init kwargs (YAML values)
        return env_settings, init_settings, file_secret_settings

    groups: GroupsConfig = GroupsConfig()
    services: ServicesConfig = ServicesConfig()
    transport: str = "http"
    host: str = "127.0.0.1"
    port: int = 8000
    scraping: ScrapingConfig = ScrapingConfig()
    academic: AcademicConfig = AcademicConfig()
    cache: CacheConfig = CacheConfig()
    vector_index: VectorIndexConfig = VectorIndexConfig()
    domains: DomainFilterConfig = DomainFilterConfig()
    log_level: str = "INFO"

    # Secrets (from env vars)
    github_pat: str | None = None
    semantic_scholar_api_key: str | None = None
    core_api_key: str | None = None
    pubmed_api_key: str | None = None
    crossref_mailto: str | None = None
    unpaywall_email: str | None = None
    doaj_api_key: str | None = None


def _resolve_config_path(cli_path: str | None = None) -> Path | None:
    """Find the config file, checking multiple locations."""
    candidates = []
    if cli_path:
        candidates.append(Path(cli_path))
    env_path = os.environ.get("RESEARCH_MCP_CONFIG")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path("config.yaml"))
    candidates.append(Path.home() / ".research-mcp" / "config.yaml")

    for path in candidates:
        if path.is_file():
            return path
    return None


def _yaml_to_flat_env(data: dict[str, Any], prefix: str = "RESEARCH_MCP_") -> dict[str, str]:
    """Flatten nested YAML dict into env-var-style keys for Pydantic Settings."""
    result: dict[str, str] = {}

    def _flatten(obj: Any, key_prefix: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _flatten(v, f"{key_prefix}{k.upper()}__" if key_prefix else f"{prefix}{k.upper()}__")
            return
        if isinstance(obj, list):
            result[key_prefix.rstrip("__")] = str(obj)
            return
        result[key_prefix.rstrip("__")] = str(obj)

    _flatten(data, "")
    return result


def load_config(config_path: str | None = None) -> ResearchMCPConfig:
    """Load config from YAML file + environment variables.

    Priority: env vars > YAML file > defaults.
    Env vars are handled by pydantic-settings automatically at construction.
    YAML values are passed as init kwargs but env vars take precedence
    via the _settings_customise_sources override.
    """
    resolved = _resolve_config_path(config_path)
    yaml_data: dict[str, Any] = {}
    if resolved:
        try:
            with open(resolved) as f:
                yaml_data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in config file {resolved}: {e}") from e

    # pydantic-settings: env vars are read at construction and override init kwargs
    # by default. We pass YAML data as init kwargs so the priority is:
    # env vars > YAML kwargs > model defaults
    config = ResearchMCPConfig(**yaml_data)

    # Resolve paths
    config.cache.db_path = str(Path(config.cache.db_path).expanduser())
    config.vector_index.db_path = str(Path(config.vector_index.db_path).expanduser())

    return config
