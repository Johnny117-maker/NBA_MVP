from datetime import date, timedelta

import pandas as pd

from src.daily_games import (
    build_form_table,
    format_tipoff,
    game_headliner,
    games_for_date,
    status_label,
    team_aliases,
    team_highlights,
)


def _player_rows(player_id, name, team, pts, reb, ast, minutes=30.0, n_games=12, last_date="2024-03-10"):
    end = pd.Timestamp(last_date)
    rows = []
    for i in range(n_games):
        rows.append(
            {
                "player_id": player_id,
                "player_name": name,
                "team": team,
                "game_id": f"{player_id}-{i}",
                "game_date": end - timedelta(days=(n_games - 1 - i) * 2),
                "season": "2023-24",
                "minutes": minutes,
                "pts": pts[i] if isinstance(pts, list) else pts,
                "reb": reb,
                "ast": ast,
            }
        )
    return rows


def _league() -> pd.DataFrame:
    rows = []
    rows += _player_rows(1, "Estrela", "BOS", 30, 5, 6)
    rows += _player_rows(2, "Pivo", "BOS", 12, 12, 1)
    rows += _player_rows(3, "Reserva", "BOS", 4, 1, 1, minutes=8.0)  # poucos minutos
    rows += _player_rows(4, "Parado", "BOS", 25, 5, 5, last_date="2024-01-01")  # inativo
    rows += _player_rows(5, "Rival", "NYK", 20, 4, 8)
    # Jogador em alta: média da temporada baixa, últimos 5 jogos altos.
    rows += _player_rows(6, "Quente", "NYK", [8] * 7 + [24] * 5, 3, 2)
    return pd.DataFrame(rows)


def test_build_form_table_has_recent_and_season_averages():
    table = build_form_table(_league()).set_index("player_id")
    hot = table.loc[6]
    assert hot["pts_recent"] == 24
    assert hot["pts_season"] == (8 * 7 + 24 * 5) / 12
    assert hot["pts_delta"] > 3
    assert table.loc[1, "team"] == "BOS"


def test_team_highlights_ranks_by_impact_and_filters_ineligible_players():
    table = build_form_table(_league())
    highlights = team_highlights(table, "BOS", top_n=5)
    names = list(highlights["player_name"])
    assert names[0] == "Estrela"
    assert "Reserva" not in names  # minutos baixos
    assert "Parado" not in names  # sem jogar há muito tempo
    assert "Cestinha" in highlights.loc[highlights["player_name"] == "Estrela", "tag"].iloc[0]
    assert "Reboteiro" in highlights.loc[highlights["player_name"] == "Pivo", "tag"].iloc[0]


def test_team_highlights_flags_hot_streak_and_respects_top_n():
    table = build_form_table(_league())
    highlights = team_highlights(table, "NYK", top_n=1)
    assert len(highlights) == 1
    all_nyk = team_highlights(table, "NYK", top_n=5)
    hot_tag = all_nyk.loc[all_nyk["player_name"] == "Quente", "tag"].iloc[0]
    assert "Em alta" in hot_tag


def test_team_highlights_matches_full_team_names_too():
    league = _league()
    league["team"] = league["team"].map({"BOS": "Boston Celtics", "NYK": "New York Knicks"})
    highlights = team_highlights(build_form_table(league), "BOS")
    assert "Estrela" in set(highlights["player_name"])
    assert team_aliases("bos") == {"BOS", "Boston Celtics"}


def test_team_highlights_empty_for_unknown_team_and_empty_table():
    table = build_form_table(_league())
    assert team_highlights(table, "LAL").empty
    assert team_highlights(build_form_table(pd.DataFrame()), "BOS").empty


def test_game_headliner_picks_highest_impact_across_teams():
    table = build_form_table(_league())
    headliner = game_headliner(team_highlights(table, "BOS"), team_highlights(table, "NYK"))
    assert headliner is not None
    assert headliner["player_name"] == "Estrela"
    assert game_headliner(pd.DataFrame(), pd.DataFrame()) is None


def test_games_for_date_filters_and_sorts_by_tipoff():
    schedule = pd.DataFrame(
        [
            {"game_id": "b", "game_date": pd.Timestamp("2026-10-23"),
             "game_datetime_utc": pd.Timestamp("2026-10-24T02:00:00Z")},
            {"game_id": "a", "game_date": pd.Timestamp("2026-10-23"),
             "game_datetime_utc": pd.Timestamp("2026-10-23T23:00:00Z")},
            {"game_id": "x", "game_date": pd.Timestamp("2026-10-24"),
             "game_datetime_utc": pd.Timestamp("2026-10-24T23:00:00Z")},
        ]
    )
    games = games_for_date(schedule, date(2026, 10, 23))
    assert list(games["game_id"]) == ["a", "b"]
    assert games_for_date(pd.DataFrame(), date(2026, 10, 23)).empty


def test_format_tipoff_shows_brasilia_and_eastern_time():
    text = format_tipoff(pd.Timestamp("2026-10-23T23:30:00Z"))
    assert "20:30 (Brasília)" in text
    assert "19:30 ET" in text
    assert format_tipoff(pd.NaT) == "Horário a confirmar"
    # 01:00 UTC: em Brasília ainda é 22:00 do dia 22 e ET 21:00 — mesmo dia.
    assert "dia seguinte" not in format_tipoff(pd.Timestamp("2026-10-23T01:00:00Z"))


def test_status_label_handles_unknown_values():
    assert status_label(1) == "Agendado"
    assert status_label(3) == "Encerrado"
    assert status_label(None) == "—"