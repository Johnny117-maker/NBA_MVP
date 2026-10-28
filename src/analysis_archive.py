"""Fotografias pré-jogo imutáveis e resultados separados, ligados à partida exata."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

import pandas as pd

from .live_store import read_live_games
from .live_types import EASTERN, LiveGame, utc_now
from .nba_teams import TEAM_ABBREVIATION_TO_NAME
from .prop_training import (
    STATS,
    PropsBundle,
    ensure_props_bundle,
    feature_table,
    load_research_history,
    project_props,
)
from .research_metrics import beta_shooting, kalman_rate

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_snapshots (
 id TEXT PRIMARY KEY, game_key TEXT NOT NULL UNIQUE, day TEXT NOT NULL,
 captured_at TEXT NOT NULL, kickoff TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_day ON daily_snapshots(day);
CREATE TRIGGER IF NOT EXISTS snapshots_no_update BEFORE UPDATE ON daily_snapshots
 BEGIN SELECT RAISE(ABORT,'Previsões pré-jogo são imutáveis'); END;
CREATE TRIGGER IF NOT EXISTS snapshots_no_delete BEFORE DELETE ON daily_snapshots
 BEGIN SELECT RAISE(ABORT,'Previsões pré-jogo são imutáveis'); END;
CREATE TABLE IF NOT EXISTS snapshot_outcomes (
 snapshot_id TEXT NOT NULL, player_id INTEGER NOT NULL, recorded_at TEXT NOT NULL,
 fingerprint TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshot_results ON snapshot_outcomes(snapshot_id,player_id);
CREATE TABLE IF NOT EXISTS research_state (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS external_metrics (
 metric TEXT NOT NULL,player_id INTEGER NOT NULL,as_of TEXT NOT NULL,known_at TEXT NOT NULL,
 value REAL NOT NULL,source TEXT NOT NULL,details TEXT NOT NULL,
 PRIMARY KEY(metric,player_id,as_of,known_at)
);
"""


def archive_path(path: str | Path) -> Path:
    path = Path(path)
    return path.with_name(path.stem + "_analysis.sqlite")


def connect_archive(path: str | Path) -> sqlite3.Connection:
    target = archive_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=20)
    connection.executescript(SCHEMA)
    return connection


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def archive_snapshot(path: str | Path, payload: dict) -> bool:
    captured = pd.Timestamp(payload["captured_at"])
    kickoff = pd.Timestamp(payload["kickoff"])
    day = payload["day"]
    if (
        captured.tzinfo is None
        or kickoff.tzinfo is None
        or captured >= kickoff
        or captured.tz_convert(EASTERN).date().isoformat() != day
        or kickoff.tz_convert(EASTERN).date().isoformat() != day
        or pd.Timestamp(payload["history_end"]).date().isoformat() >= day
        or payload["state"] != "pre"
        or not payload["players"]
    ):
        raise ValueError(
            "A fotografia deve ser registrada no dia NBA, antes do início, com histórico anterior."
        )
    if payload.get("model", {}).get("train_end", payload["history_end"]) >= day:
        raise ValueError("O modelo contém dados da data alvo ou posteriores.")
    body = _json(payload)
    digest = hashlib.sha256(body.encode()).hexdigest()
    with connect_archive(path) as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO daily_snapshots VALUES (?,?,?,?,?,?,?)",
            (digest[:24], payload["game_key"], day, captured.isoformat(), kickoff.isoformat(), body, digest),
        )
        return cursor.rowcount > 0


def read_snapshots(
    path: str | Path, day: str | None = None, *, for_resolution: bool = False, limit: int | None = None
) -> list[dict]:
    if not archive_path(path).exists():
        return []
    conditions, parameters = [], []
    if day:
        conditions.append("day=?")
        parameters.append(day)
    if for_resolution:
        conditions.append(
            "(day>=? OR (SELECT COUNT(DISTINCT player_id) FROM snapshot_outcomes "
            "WHERE snapshot_id=daily_snapshots.id)<json_array_length(payload,'$.players'))"
        )
        parameters.append((utc_now().astimezone(EASTERN).date() - timedelta(days=14)).isoformat())
    query = "SELECT id,payload,sha256 FROM daily_snapshots "
    if conditions:
        query += "WHERE " + " AND ".join(conditions) + " "
    query += "ORDER BY day DESC,kickoff,game_key"
    if limit is not None:
        query += f" LIMIT {max(1, int(limit))}"
    with connect_archive(path) as connection:
        rows = connection.execute(
            query,
            parameters,
        ).fetchall()
    results = []
    for key, body, digest in rows:
        if hashlib.sha256(body.encode()).hexdigest() != digest:
            raise ValueError("A integridade de uma fotografia diária não pôde ser confirmada.")
        results.append({**json.loads(body), "id": key, "sha256": digest})
    return results


def shooting_context(rows: pd.DataFrame) -> dict:
    recent = rows.tail(10)
    fga, fta = float(recent["fga"].sum()), float(recent["fta"].sum())
    attempts = fga + 0.44 * fta
    individual = attempts + float(recent["ast"].sum() + recent["tov"].sum())
    return {
        "ts_pct": float(recent["pts"].sum()) / (2 * attempts) if attempts > 0 else None,
        "ast_ratio": 100 * float(recent["ast"].sum()) / individual if individual > 0 else None,
        "tov_ratio": 100 * float(recent["tov"].sum()) / individual if individual > 0 else None,
        "fg3_posterior": beta_shooting(float(recent["fg3m"].sum()), float(recent["fg3a"].sum()), 0.36),
        "ft_posterior": beta_shooting(float(recent["ftm"].sum()), fta, 0.78),
        "dynamic": {s: kalman_rate(recent[s], recent["minutes"]) for s in STATS},
    }


def highlighted_players(history: pd.DataFrame, game: LiveGame) -> pd.DataFrame:
    before = history.loc[history["game_date"].lt(pd.Timestamp(game.day))]
    candidates = []
    for pid, rows in before.groupby("player_id", sort=False):
        latest = rows.iloc[-1]
        if (
            latest["team"] not in {game.home, game.away}
            or latest["season"] != game.season
            or (pd.Timestamp(game.day) - latest["game_date"]).days > 14
            or len(rows) < 3
        ):
            continue
        recent = rows.tail(5)
        if float(recent["minutes"].mean()) < 15:
            continue
        candidates.append(
            {
                "player_id": int(pid),
                "team": latest["team"],
                "player_name": latest["player_name"],
                "impact": float((recent["pts"] + 0.7 * recent["reb"] + recent["ast"]).mean()),
            }
        )
    table = pd.DataFrame(candidates)
    if table.empty:
        return table
    return table.sort_values("impact", ascending=False).groupby("team", sort=False).head(3)


def _future_rows(history: pd.DataFrame, games: list[LiveGame]) -> tuple[pd.DataFrame, dict]:
    rows = []
    selections = {}
    for game in games:
        chosen = highlighted_players(history, game)
        if chosen.empty or set(chosen["team"]) != {game.home, game.away}:
            continue
        selections[game.key] = chosen
        for player in chosen.to_dict("records"):
            row: dict = dict.fromkeys(history.columns, float("nan"))
            row.update(
                {
                    **player,
                    "game_id": game.key,
                    "game_date": pd.Timestamp(game.day),
                    "season": game.season,
                    "opponent": game.away if player["team"] == game.home else game.home,
                    "is_home": int(player["team"] == game.home),
                }
            )
            rows.append(row)
    return pd.DataFrame(rows), selections


def create_daily_snapshots(
    path: str | Path,
    games: list[LiveGame],
    history: pd.DataFrame,
    bundle: PropsBundle | None = None,
    now: datetime | None = None,
) -> int:
    moment = now or utc_now()
    selected_day = moment.astimezone(EASTERN).date().isoformat()
    existing = {row["game_key"] for row in read_snapshots(path, selected_day)}
    history = history.loc[history["game_date"].lt(pd.Timestamp(selected_day))].copy()
    eligible = [
        g
        for g in games
        if g.regular_season
        and g.state == "pre"
        and g.key not in existing
        and g.kickoff
        and pd.Timestamp(g.kickoff) > pd.Timestamp(moment)
        and g.day == moment.astimezone(EASTERN).date().isoformat()
    ]
    if not eligible or history.empty:
        return 0
    future, selections = _future_rows(history, eligible)
    if future.empty:
        return 0
    table = feature_table(history, future)
    added = 0
    for game in eligible:
        if game.key not in selections:
            continue
        players = []
        for row in table.loc[table["game_id"].eq(game.key)].itertuples(index=False):
            values = pd.Series(row._asdict())
            player_history = history.loc[history["player_id"].eq(row.player_id)]
            projection = project_props(values, bundle)
            players.append(
                {
                    "player_id": int(row.player_id),
                    "name": row.player_name,
                    "team": row.team,
                    "history_games": len(player_history),
                    "last_game": player_history["game_date"].max().date().isoformat(),
                    "participation": "Participação não confirmada; seleção pelo histórico recente",
                    "usage_pct_estimate": float(values["usage_10"]) if pd.notna(values["usage_10"]) else None,
                    "context": shooting_context(player_history),
                    **projection,
                }
            )
        # Confere novamente APÓS o cálculo/treino: não arquiva se a partida já começou.
        captured = now or utc_now()
        if pd.Timestamp(game.kickoff) <= pd.Timestamp(captured):
            continue
        payload = {
            "schema_version": 1,
            "game_key": game.key,
            "day": game.day,
            "season": game.season,
            "home": game.home,
            "away": game.away,
            "state": "pre",
            "kickoff": game.kickoff,
            "captured_at": captured.isoformat(),
            "source": game.source,
            "source_fetched_at": game.fetched_at,
            "schedule_archive": game.archive,
            "history_end": history["game_date"].max().date().isoformat(),
            "model": bundle.manifest
            if bundle
            else {
                "id": "gamma-poisson-v1",
                "train_end": history["game_date"].max().date().isoformat(),
                "status": "Somente Bayes; XGBoost indisponível",
            },
            "players": players,
            "line_source": "Referência estatística; não é uma linha de casa de apostas",
        }
        added += int(archive_snapshot(path, payload))
    return added


def resolve_snapshots(path: str | Path) -> int:
    snapshots = read_snapshots(path, for_resolution=True, limit=200)
    if not snapshots or not Path(path).exists():
        return 0
    added = 0
    with sqlite3.connect(path, timeout=15) as history, connect_archive(path) as archive:
        for snapshot in snapshots:
            game = history.execute(
                "SELECT game_id,home_points,away_points FROM games WHERE date(game_date)=? "
                "AND home_team=? AND away_team=?",
                (
                    snapshot["day"],
                    TEAM_ABBREVIATION_TO_NAME[snapshot["home"]],
                    TEAM_ABBREVIATION_TO_NAME[snapshot["away"]],
                ),
            ).fetchone()
            if game is None:
                continue
            all_rows = pd.read_sql_query(
                "SELECT player_id,team,minutes,pts,reb,ast FROM player_game_stats WHERE game_id=?",
                history,
                params=(game[0],),
            )
            complete = all(
                len(team := all_rows.loc[all_rows["team"].eq(code)]) >= 5
                and int(team["pts"].sum()) == score
                and float(team["minutes"].sum()) >= 230
                for code, score in ((snapshot["home"], game[1]), (snapshot["away"], game[2]))
            )
            for player in snapshot["players"]:
                pid = player["player_id"]
                alias = history.execute(
                    "SELECT canonical_id FROM player_id_aliases WHERE alias=?", (pid,)
                ).fetchone()
                canonical = int(alias[0]) if alias else pid
                actual = all_rows.loc[all_rows["player_id"].eq(canonical)]
                if actual.empty and not complete:
                    continue
                participated = not actual.empty and float(actual.iloc[0]["minutes"]) > 0
                outcome = {
                    "game_id": game[0],
                    "status": "Jogou" if participated else "Sem participação",
                    "actual": {s: float(actual.iloc[0][s]) for s in STATS} if participated else None,
                }
                body = _json(outcome)
                fingerprint = hashlib.sha256(body.encode()).hexdigest()
                latest = archive.execute(
                    "SELECT fingerprint FROM snapshot_outcomes WHERE snapshot_id=? AND player_id=? "
                    "ORDER BY rowid DESC LIMIT 1",
                    (snapshot["id"], pid),
                ).fetchone()
                if latest and latest[0] == fingerprint:
                    continue
                cursor = archive.execute(
                    "INSERT OR IGNORE INTO snapshot_outcomes VALUES (?,?,?,?,?)",
                    (snapshot["id"], pid, utc_now().isoformat(), fingerprint, body),
                )
                added += int(cursor.rowcount > 0)
    return added


def snapshot_table(path: str | Path, day: str) -> pd.DataFrame:
    rows = []
    snapshots = read_snapshots(path, day)
    if not snapshots:
        return pd.DataFrame()
    with connect_archive(path) as connection:
        for snapshot in snapshots:
            for player in snapshot["players"]:
                outcome_row = connection.execute(
                    "SELECT payload FROM snapshot_outcomes WHERE snapshot_id=? AND player_id=? "
                    "ORDER BY rowid DESC LIMIT 1",
                    (snapshot["id"], player["player_id"]),
                ).fetchone()
                outcome = json.loads(outcome_row[0]) if outcome_row else {}
                for stat, prediction in player["stats"].items():
                    actual = (outcome.get("actual") or {}).get(stat)
                    rows.append(
                        {
                            "snapshot_id": snapshot["id"],
                            "game_key": snapshot["game_key"],
                            "captured_at": snapshot["captured_at"],
                            "matchup": f"{snapshot['away']} @ {snapshot['home']}",
                            "player_id": player["player_id"],
                            "player": player["name"],
                            "team": player["team"],
                            "stat": stat,
                            **prediction,
                            "actual": actual,
                            "error": actual - prediction["projected"] if actual is not None else None,
                            "status": outcome.get("status", "Aguardando resultado"),
                            "model": snapshot["model"]["id"],
                        }
                    )
    return pd.DataFrame(rows)


def apply_frozen_pregame_props(path: str | Path, rows: list[dict], day: str) -> list[dict]:
    """Os cartões dos destaques usam a mesma projeção de referência preservada no arquivo.

    Durante o jogo, a previsão condicional continua usando observações recentes;
    nunca substitui nem altera a fotografia pré-jogo.
    """
    frozen = {}
    for snapshot in read_snapshots(path, day):
        for player in snapshot["players"]:
            for stat, prediction in player["stats"].items():
                frozen[(snapshot["game_key"], player["player_id"], stat)] = (snapshot, prediction)
    result = []
    for row in rows:
        entry = frozen.get((row["game_key"], row["player_id"], row["stat"]))
        if row["state"] == "pre" and entry is not None:
            snapshot, prediction = entry
            side = "Over" if prediction["over"] >= prediction["under"] else "Under"
            row = {
                **row,
                **{key: prediction[key] for key in ("projected", "low", "high", "line", "over", "under")},
                "side": side,
                "probability": max(prediction["over"], prediction["under"]),
                "line_source": "Registro pré-jogo · referência estatística",
                "model_id": snapshot["model"]["id"],
                "snapshot_id": snapshot["id"],
            }
        result.append(row)
    return sorted(result, key=lambda r: (r["state"] == "live", r["probability"]), reverse=True)


def snapshot_html(snapshot: dict) -> str:
    stamp = pd.Timestamp(snapshot["captured_at"]).tz_convert("America/Sao_Paulo")
    rows = []
    for player in snapshot["players"]:
        numbers = "".join(
            f"<td>{player['stats'][s]['projected']:.1f} "
            f"<small>({player['stats'][s]['low']:.0f}–{player['stats'][s]['high']:.0f})</small></td>"
            for s in STATS
        )
        rows.append(f"<tr><td>{escape(player['name'])}</td><td>{escape(player['team'])}</td>{numbers}</tr>")
    return (
        '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Previsão pré-jogo</title>'
        "<style>body{font:16px system-ui;margin:40px;color:#152538}table{border-collapse:collapse;"
        "width:100%}td,th{padding:12px;text-align:left;border-bottom:1px solid #ccd3dd}"
        "small{color:#536477}p{line-height:1.5}@media print{body{margin:12mm}}</style>"
        f"<h1>{escape(snapshot['away'])} @ {escape(snapshot['home'])}</h1>"
        f"<p>Dia NBA: {escape(snapshot['day'])}<br>Registrado antes da partida: "
        f"{stamp:%d/%m/%Y %H:%M:%S} "
        "(Brasília)<br>Faixa preditiva P10–P90; participação dos atletas não confirmada.</p>"
        "<table><tr><th>Jogador</th><th>Time</th><th>PTS previstos</th><th>REB previstos</th>"
        f"<th>AST previstos</th></tr>{''.join(rows)}</table>"
        f"<p>Modelo: {escape(snapshot['model']['id'])}<br>Histórico usado até: "
        f"{escape(snapshot['history_end'])}<br>Fonte do calendário: {escape(snapshot['source'])}</p>"
        f"<p>Fotografia original preservada. SHA-256: {escape(snapshot.get('sha256', ''))}</p></html>"
    )


def run_daily_analysis(path: str | Path, *, now: datetime | None = None) -> dict:
    moment = now or utc_now()
    day = moment.astimezone(EASTERN).date().isoformat()
    games = read_live_games(path, day)
    pending = {g.key for g in games if g.state == "pre" and g.kickoff and pd.Timestamp(g.kickoff) > moment}
    pending -= {s["game_key"] for s in read_snapshots(path, day)}
    result: dict = {"new_snapshots": 0, "resolved": resolve_snapshots(path)}
    if pending:
        history = load_research_history(path, day)
        if history.empty:
            return {**result, "status": "Aguardando histórico de jogadores"}
        bundle = None
        try:
            bundle = ensure_props_bundle(history, Path(path).parent.parent / "models" / "props")
            result["model"] = bundle.manifest["id"]
        except (ImportError, ValueError) as error:
            result["model_status"] = str(error)
            logging.getLogger(__name__).warning("Modelo de props: %s", error)
        result["new_snapshots"] = create_daily_snapshots(path, games, history, bundle, now)
    output = Path(path).parent / "analyses" / day
    for snapshot in read_snapshots(path, day):
        output.mkdir(parents=True, exist_ok=True)
        target = output / f"{snapshot['away']}_{snapshot['home']}_{snapshot['id']}.html"
        if not target.exists():
            with target.open("x", encoding="utf-8") as file:
                file.write(snapshot_html(snapshot))
    result["checked_at"] = utc_now().isoformat()
    with connect_archive(path) as connection:
        connection.execute("INSERT OR REPLACE INTO research_state VALUES ('status',?)", (_json(result),))
    return result
