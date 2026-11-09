from __future__ import annotations

import itertools
import sqlite3
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from src.player_data import generate_demo_player_games
from src.shot_features import THREE_POINT_ZONES, ZONES
from src.shot_storage import upsert_player_shots
from src.store import init_db, log_model_training, upsert_games, upsert_player_games


@pytest.fixture(autouse=True)
def no_real_waiting_between_retries(monkeypatch):
    """As esperas entre retentativas de rede não devem atrasar a suíte."""
    monkeypatch.setattr("src.http_retry.default_sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def disable_background_network_in_tests(monkeypatch):
    monkeypatch.setenv("NBA_AUTO_SYNC", "0")

# Times reais só para nomear os jogos sintéticos de forma plausível — os
# testes de página não dependem de nenhum desses times em particular.
FIXTURE_TEAMS = [
    "Boston Celtics",
    "New York Knicks",
    "Miami Heat",
    "Milwaukee Bucks",
    "Los Angeles Lakers",
    "Golden State Warriors",
]
FIXTURE_SEASONS = ["2022-23", "2023-24"]

# IDs fora da faixa 1..~150 usada pelo roster de `generate_demo_player_games`
# — evita qualquer colisão acidental entre as duas fontes sintéticas.
FIXTURE_SHOT_PLAYERS = [
    (9001, "Fixture Player One", FIXTURE_TEAMS[0], 11),
    (9002, "Fixture Player Two", FIXTURE_TEAMS[1], 12),
    (9003, "Fixture Player Three", FIXTURE_TEAMS[2], 13),
]


def _synthetic_raw_games(seed: int = 1) -> pd.DataFrame:
    """Jogos brutos (data, placar) suficientes para `train_models` (mínimo 50).

    Todo par de times joga uma vez em casa e uma fora, em cada temporada —
    `itertools.permutations` de 6 times dá 30 jogos por temporada, 60 no
    total, com folga sobre o mínimo.
    """
    rng = np.random.default_rng(seed)
    rows = []
    game_id = 0
    for season_index, season in enumerate(FIXTURE_SEASONS):
        season_start = pd.Timestamp("2022-10-18") + pd.DateOffset(years=season_index)
        for day, (home, away) in enumerate(itertools.permutations(FIXTURE_TEAMS, 2)):
            game_id += 1
            home_points = max(80, int(rng.normal(112, 10)))
            away_points = max(80, int(rng.normal(108, 10)))
            if home_points == away_points:
                home_points += 1
            rows.append(
                {
                    "game_id": f"TESTGAME{game_id:05d}",
                    "game_date": season_start + timedelta(days=day * 2),
                    "season": season,
                    "home_team": home,
                    "away_team": away,
                    "home_points": home_points,
                    "away_points": away_points,
                }
            )
    return pd.DataFrame(rows)


def _synthetic_shots_for_player(
    player_id: int, player_name: str, team_name: str, seed: int, games_per_season: int = 20
) -> pd.DataFrame:
    """Arremessos sintéticos de um jogador, suficientes (com folga) para o
    mínimo de 30 jogos-de-jogador exigido por `train_zone_models`.
    """
    rng = np.random.default_rng(seed)
    opponents = [team for team in FIXTURE_TEAMS if team != team_name]
    rows = []
    game_date = pd.Timestamp("2022-10-18")

    for season in FIXTURE_SEASONS:
        for game_number in range(games_per_season):
            opponent = opponents[game_number % len(opponents)]
            game_id = f"TESTSHOTGAME-{player_id}-{season}-{game_number:03d}"
            game_date = game_date + timedelta(days=3)
            n_shots = int(rng.integers(8, 16))
            zones_chosen = rng.choice(ZONES, size=n_shots)
            for event_id, zone in enumerate(zones_chosen, start=1):
                made = bool(rng.random() < 0.45)
                shot_type = "3PT Field Goal" if zone in THREE_POINT_ZONES else "2PT Field Goal"
                rows.append(
                    {
                        "player_id": player_id,
                        "player_name": player_name,
                        "game_id": game_id,
                        "game_event_id": event_id,
                        "season": season,
                        "game_date": game_date,
                        "team_id": player_id,
                        "team_name": team_name,
                        "opponent": opponent,
                        "period": 1,
                        "minutes_remaining": 5,
                        "seconds_remaining": 0,
                        "event_type": "Made Shot" if made else "Missed Shot",
                        "action_type": "Jump Shot",
                        "shot_type": shot_type,
                        "shot_zone_basic": zone,
                        "shot_zone_area": "Center(C)",
                        "shot_zone_range": "Less Than 8 ft.",
                        "shot_distance": 10.0,
                        "loc_x": 0,
                        "loc_y": 100,
                        "loc_x_ft": 0.0,
                        "loc_y_ft": 10.0,
                        "shot_attempted": 1,
                        "shot_made": made,
                        "source": "test-fixture",
                    }
                )
    return pd.DataFrame(rows)


_TEAM_METRICS = {
    "accuracy": 0.62,
    "log_loss": 0.65,
    "brier_score": 0.22,
    "home_points_mae": 9.5,
    "away_points_mae": 9.8,
}
_PLAYER_METRICS = {
    "minutes_mae": 5.2,
    "pts_mae": 4.1,
    "reb_mae": 2.0,
    "ast_mae": 1.3,
    "pts_interval_coverage": 0.78,
    "reb_interval_coverage": 0.80,
    "ast_interval_coverage": 0.81,
    "n_folds": 5,
}
_ZONE_METRICS = {
    "fg_points_mae": 2.9,
    **{f"share_mae_{zone}": 0.1 for zone in ZONES},
    "n_folds": 5,
}


@pytest.fixture(scope="session")
def _app_db_path(tmp_path_factory: pytest.TempPathFactory):
    """Constrói o banco de teste uma única vez por sessão (caro: gera times,
    jogadores e arremessos sintéticos) — o fixture por-teste
    (`app_db`, abaixo) só aponta pra ele via monkeypatch, rápido.
    """
    db_path = tmp_path_factory.mktemp("nba_test_db") / "nba.db"
    init_db(db_path)

    upsert_games(_synthetic_raw_games(), db_path)
    upsert_player_games(generate_demo_player_games(games_per_team=15), db_path)
    for player_id, player_name, team_name, seed in FIXTURE_SHOT_PLAYERS:
        upsert_player_shots(
            _synthetic_shots_for_player(player_id, player_name, team_name, seed), db_path
        )

    log_model_training("team", 60, _TEAM_METRICS, db_path)
    log_model_training("player", 500, _PLAYER_METRICS, db_path)
    log_model_training("zone", 120, _ZONE_METRICS, db_path)

    return db_path


@pytest.fixture
def app_db(_app_db_path, monkeypatch: pytest.MonkeyPatch):
    """Redireciona `src.store.DEFAULT_DB_PATH` para o banco de teste pequeno e
    determinístico, em vez do banco real de desenvolvimento (`data/nba.db`,
    que já passou de 1,6 milhão de arremessos coletados nesta sessão).

    Funciona porque toda página faz `from src.store import DEFAULT_DB_PATH`
    dentro do próprio script — o `AppTest` reexecuta esse `import` do zero a
    cada `.run()`, então ele sempre lê o valor atual do atributo no módulo
    (já trocado por este monkeypatch), não um valor "congelado" de quando
    `src.store` foi importado pela primeira vez no processo de teste.
    """
    monkeypatch.setattr("src.store.DEFAULT_DB_PATH", _app_db_path)
    return _app_db_path


@pytest.fixture
def cloud_data(_app_db_path, tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Simula o app online: cópia do banco de teste (com os bancos auxiliares já
    criados, como no pacote publicado) em ``NBA_DATA_HOME`` e ``NBA_DEPLOY_MODE=cloud``.

    A consulta de atualização ao Release é trocada por um estado "em dia" para
    nenhum teste acessar a rede. Ao final o guarda de somente leitura é removido.
    """
    import shutil

    from src import cloud_bootstrap, deploy_mode
    from src.analysis_archive import connect_archive
    from src.history_store import connect_history
    from src.live_store import connect_state
    from src.ui import cloud

    home = tmp_path / "home"
    (home / "data").mkdir(parents=True)
    db = home / "data" / "nba.db"
    shutil.copy2(_app_db_path, db)
    for connect in (connect_history, connect_state, connect_archive):
        connect(db).close()
    with sqlite3.connect(db.with_name("nba_history.sqlite")) as history:
        history.execute("PRAGMA journal_mode=DELETE")  # como no pacote: sem -wal/-shm ao lado
    monkeypatch.setenv("NBA_DATA_HOME", str(home))
    for name in ("NBA_DEPLOY_MODE", "NBA_AUTO_SYNC"):
        monkeypatch.setenv(name, "x")  # registra o valor original para restaurar no fim
    monkeypatch.setenv("NBA_DEPLOY_MODE", "cloud")
    monkeypatch.setattr("src.store.DEFAULT_DB_PATH", db)
    current = cloud_bootstrap.BundleStatus(cloud_bootstrap.STATE_CURRENT, "teste", "2026-11-09T12:00:00Z")
    monkeypatch.setattr(cloud_bootstrap, "sync_bundle", lambda *args, **kwargs: current)
    cloud._synchronized_status.clear()
    yield db
    cloud._synchronized_status.clear()
    deploy_mode.uninstall_read_only_guard()
