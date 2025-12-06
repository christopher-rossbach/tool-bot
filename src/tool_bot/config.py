from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def _get(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(name, default)
    return val


def _get_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in {"1", "true", "yes", "on"}


def _split(name: str) -> List[str]:
    val = os.environ.get(name, "")
    return [x.strip() for x in val.split(",") if x.strip()]


@dataclass
class Config:
    matrix_homeserver: str
    matrix_user: Optional[str]
    matrix_password: Optional[str]
    matrix_access_token: Optional[str]
    allowed_users: List[str]
    llm_provider: str
    openai_api_key: Optional[str]
    anthropic_api_key: Optional[str]
    todoist_token: Optional[str]
    whisper_model: str
    enable_e2ee: bool
    enable_anki: bool
    anki_connect_url: str

    @staticmethod
    def load() -> "Config":
        # Try loading from JSON config file first
        config_path = os.environ.get("CONFIG_PATH", "/app/config/config.json")
        if Path(config_path).exists():
            return Config._load_from_json(config_path)
        
        # Fall back to environment variables
        return Config._load_from_env()
    
    @staticmethod
    def _load_from_json(path: str) -> "Config":
        with open(path, "r") as f:
            data: Dict[str, Any] = json.load(f)
        
        homeserver = data.get("matrix_homeserver", "")
        if not homeserver:
            raise ValueError("matrix_homeserver is required in config")
        
        return Config(
            matrix_homeserver=homeserver,
            matrix_user=data.get("matrix_user"),
            matrix_password=data.get("matrix_password"),
            matrix_access_token=data.get("matrix_access_token"),
            allowed_users=data.get("allowed_users", []),
            llm_provider=data.get("llm_provider", "openai"),
            openai_api_key=data.get("openai_api_key"),
            anthropic_api_key=data.get("anthropic_api_key"),
            todoist_token=data.get("todoist_token"),
            whisper_model=data.get("whisper_model", "base"),
            enable_e2ee=data.get("enable_e2ee", False),
            enable_anki=data.get("enable_anki", True),
            anki_connect_url=data.get("anki_connect_url", "http://localhost:8765"),
        )
    
    @staticmethod
    def _load_from_env() -> "Config":
        homeserver = _get("MATRIX_HOMESERVER", "")
        if not homeserver:
            raise ValueError("MATRIX_HOMESERVER is required")
        return Config(
            matrix_homeserver=homeserver,
            matrix_user=_get("MATRIX_USER"),
            matrix_password=_get("MATRIX_PASSWORD"),
            matrix_access_token=_get("MATRIX_ACCESS_TOKEN"),
            allowed_users=_split("ALLOWED_USERS"),
            llm_provider=_get("LLM_PROVIDER", "openai"),
            openai_api_key=_get("OPENAI_API_KEY"),
            anthropic_api_key=_get("ANTHROPIC_API_KEY"),
            todoist_token=_get("TODOIST_TOKEN"),
            whisper_model=_get("WHISPER_MODEL", "base"),
            enable_e2ee=_get_bool("ENABLE_E2EE", False),
            enable_anki=_get_bool("ENABLE_ANKI", True),
            anki_connect_url=_get("ANKI_CONNECT_URL", "http://localhost:8765"),
        )
