from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path

from .live_providers import ApiKeys


def load_api_keys(provided: Mapping | None = None) -> ApiKeys:
    """Lê apenas o arquivo protegido do projeto e variáveis do processo; nunca grava chaves."""
    path = Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"
    settings: dict = dict(provided) if provided is not None else {}
    if provided is None and path.exists():
        try:
            with path.open("rb") as stream:
                settings = tomllib.load(stream).get("providers", {})
        except (OSError, tomllib.TOMLDecodeError):
            raise ValueError(
                "Não foi possível ler .streamlit/secrets.toml. Confira o formato TOML."
            ) from None

    def value(name: str, env: str, default: str = "") -> str:
        return str(os.environ.get(env) or settings.get(name) or default).strip()

    return ApiKeys(
        value("api_sports_key", "NBA_API_SPORTS_KEY"),
        value("rapidapi_key", "NBA_RAPIDAPI_KEY"),
        value("balldontlie_key", "NBA_BALLDONTLIE_KEY"),
        value("odds_api_key", "NBA_ODDS_API_KEY"),
        value("balldontlie_plan", "NBA_BDL_PLAN", "free"),
    )
