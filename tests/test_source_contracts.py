"""Testes de contrato: o formato das respostas externas que o código consome.

Usam as amostras de `tests/contracts/` (ver o campo `_nota` de cada uma); nenhuma chamada de rede.
Se uma fonte mudar o esquema, a amostra atualizada deve falhar aqui com uma mensagem clara.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.history_sources import select_assets
from src.live_providers import ProviderError, parse_espn_board, parse_nba_board
from src.nba_client import PLAYER_RAW_COLUMNS, TEAM_RAW_COLUMNS, pair_home_away

CONTRACTS = Path(__file__).parent / "contracts"


def _load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _frame(name: str) -> pd.DataFrame:
    result_set = _load(name)["resultSets"][0]
    return pd.DataFrame(result_set["rowSet"], columns=result_set["headers"])


def test_every_sample_declares_that_it_is_not_a_live_recording():
    for path in CONTRACTS.glob("*.json"):
        assert "não capturada ao vivo" in json.loads(path.read_text(encoding="utf-8"))["_nota"]


def test_nba_scoreboard_contract():
    games = parse_nba_board(_load("nba_scoreboard.json"))
    assert [(g.home, g.away, g.state) for g in games] == [("CLE", "PHI", "final"), ("BOS", "NYK", "pre")]
    assert (games[0].home_score, games[0].away_score) == (119, 95)
    # o dia vem do horário de início convertido para o fuso Eastern (dia NBA)
    assert [g.day for g in games] == ["2026-11-07", "2026-11-08"]
    assert all(g.regular_season for g in games)


def test_nba_scoreboard_with_a_changed_schema_is_rejected_clearly():
    payload = _load("nba_scoreboard.json")
    payload["scoreboard"]["games"] = {"mudou": "agora é um objeto"}
    with pytest.raises(ProviderError, match="formato inesperado"):
        parse_nba_board(payload)
    with pytest.raises(ProviderError, match="formato inesperado"):
        parse_nba_board({"placar": {}})


def test_espn_scoreboard_contract():
    games = parse_espn_board(_load("espn_scoreboard.json"))
    assert len(games) == 1
    game = games[0]
    assert (game.home, game.away, game.state) == ("CLE", "PHI", "final")
    assert (game.home_score, game.away_score) == (119, 95)


def test_espn_scoreboard_with_a_changed_schema_is_rejected_clearly():
    with pytest.raises(ProviderError, match="formato inesperado"):
        parse_espn_board({"events": "mudou"})


def test_league_game_log_contract_has_every_column_the_client_reads():
    teams, players = _frame("league_gamelog_teams.json"), _frame("league_gamelog_players.json")
    assert set(TEAM_RAW_COLUMNS) <= set(teams.columns)
    assert set(PLAYER_RAW_COLUMNS) <= set(players.columns)
    paired = pair_home_away(teams.assign(GAME_DATE=pd.to_datetime(teams["GAME_DATE"]), season="2026-27"))
    assert len(paired) == 1
    row = paired.iloc[0]
    assert (row["home_points"], row["away_points"]) == (119, 95)


def test_history_catalog_contract_selects_only_known_public_assets():
    releases = _load("history_catalog.json")["releases"]
    assets = select_assets(releases, 2026, 2027)
    assert [(a.tag, a.name, a.year) for a in assets] == [
        ("nba_stats_schedules", "nba_stats_schedule_2026.parquet", 2026)
    ]
    renamed = json.loads(json.dumps(releases).replace("browser_download_url", "url_nova"))
    assert select_assets(renamed, 2026, 2027) == []
