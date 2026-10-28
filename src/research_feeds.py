"""Coleta nba_api e importação com data de disponibilidade, sem reconstruir métricas proprietárias."""

from __future__ import annotations

import json
import math
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from .analysis_archive import connect_archive
from .live_types import utc_now
from .research_metrics import defended_rim

METRICS = ("LEBRON", "O-LEBRON", "D-LEBRON", "DARKO DPM", "RAPM local", "DFG% <6ft", "Gravity local (ft)")


def import_metrics(path: str | Path, rows: pd.DataFrame, *, now=None) -> int:
    required = {"metric", "player_id", "as_of", "value", "source"}
    if not required.issubset(rows) or len(rows) > 50000 or rows.empty:
        raise ValueError("CSV exige metric, player_id, as_of, value e source; máximo de 50 mil linhas.")
    moment = now or utc_now()
    records = []
    for row in rows.to_dict("records"):
        metric = str(row["metric"])
        pid = float(row["player_id"])
        value = float(row["value"])
        as_of = pd.Timestamp(row["as_of"]).date()
        source = str(row["source"])
        parsed = urlparse(source)
        hostname = (parsed.hostname or "").lower()
        if (
            metric not in METRICS
            or not math.isfinite(pid)
            or pid <= 0
            or pid != int(pid)
            or not math.isfinite(value)
            or as_of > moment.date()
            or parsed.scheme not in {"http", "https"}
            or not hostname
        ):
            raise ValueError("Métrica, ID NBA, data de referência ou fonte inválidos.")
        if "LEBRON" in metric and not (
            hostname == "bball-index.com" or hostname.endswith(".bball-index.com")
        ):
            raise ValueError("LEBRON deve indicar a publicação do Basketball Index como fonte.")
        if metric == "DARKO DPM" and not (hostname == "darko.app" or hostname.endswith(".darko.app")):
            raise ValueError("DARKO DPM deve indicar a publicação DARKO como fonte.")
        if metric == "DFG% <6ft" and not 0 <= value <= 1:
            raise ValueError("DFG% deve ser uma proporção entre 0 e 1.")
        detail = row.get("details", "Importado de arquivo; procedência declarada pelo usuário")
        records.append((metric, int(pid), as_of.isoformat(), moment.isoformat(), value, source, str(detail)))
    with connect_archive(path) as connection:
        connection.executemany("INSERT OR IGNORE INTO external_metrics VALUES (?,?,?,?,?,?,?)", records)
    return len(records)


def read_metrics(path: str | Path, *, player_id: int | None = None, known_before=None) -> pd.DataFrame:
    with connect_archive(path) as connection:
        rows = pd.read_sql_query(
            "SELECT * FROM external_metrics ORDER BY as_of DESC,known_at DESC", connection
        )
    if player_id is not None:
        rows = rows.loc[rows["player_id"].eq(player_id)]
    if known_before is not None:
        rows = rows.loc[pd.to_datetime(rows["known_at"], utc=True).le(pd.Timestamp(known_before))]
    return rows.drop_duplicates(["metric", "player_id"]).reset_index(drop=True)


def collect_rim_defense(path: str | Path, season: str, through: date) -> int:
    from nba_api.stats.endpoints.leaguedashptdefend import LeagueDashPtDefend

    if not re.fullmatch(r"\d{4}-\d{2}", season) or through >= utc_now().date():
        raise ValueError("Use uma temporada NBA e uma data de corte anterior a hoje.")
    response = LeagueDashPtDefend(
        defense_category="Less Than 6Ft",
        season=season,
        per_mode_simple="Totals",
        date_to_nullable=through.strftime("%m/%d/%Y"),
        timeout=8,
    ).get_data_frames()[0]
    required = {"CLOSE_DEF_PERSON_ID", "D_FGM", "D_FGA", "NORMAL_FG_PCT"}
    if not required.issubset(response):
        raise ValueError("O schema de defesa da NBA mudou; a resposta não foi importada.")
    rows = []
    for row in response.to_dict("records"):
        result = defended_rim(float(row["D_FGM"]), float(row["D_FGA"]), float(row["NORMAL_FG_PCT"]))
        if result["dfg_pct"] is None:
            continue
        rows.append(
            {
                "metric": "DFG% <6ft",
                "player_id": row["CLOSE_DEF_PERSON_ID"],
                "as_of": through,
                "value": result["dfg_pct"],
                "source": "https://www.nba.com/stats/players/defense-dash-lt6",
                "details": json.dumps({**result, "season": season, "zone": "Less Than 6Ft"}),
            }
        )
    return import_metrics(path, pd.DataFrame(rows)) if rows else 0


def collect_rim_daily(path: str | Path, day: date) -> dict:
    """Uma tentativa pública/dia; falha da NBA não bloqueia as previsões arquivadas."""
    with connect_archive(path) as connection:
        previous = connection.execute("SELECT value FROM research_state WHERE key='rim_attempt'").fetchone()
        if previous and json.loads(previous[0]).get("day") == day.isoformat():
            return json.loads(previous[0])
        state: dict = {"day": day.isoformat(), "status": "consultando"}
        connection.execute(
            "INSERT OR REPLACE INTO research_state VALUES ('rim_attempt',?)", (json.dumps(state),)
        )
    from .live_types import current_season

    try:
        state = {
            **state,
            "rows": collect_rim_defense(path, current_season(day), day - timedelta(days=1)),
            "status": "ok",
        }
    except Exception as error:
        state = {**state, "status": "indisponível", "error": type(error).__name__}
    with connect_archive(path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO research_state VALUES ('rim_attempt',?)", (json.dumps(state),)
        )
    return state


def fetch_rapm_inputs(game_id: str, output: Path) -> list[Path]:
    """Guarda PBP e rotações originais para auditoria e montagem de stints.

    Não transforma substituições incompletas em posses inventadas. O ajuste RAPM
    recebe stints validados com dez jogadores e exposição medida.
    """
    from nba_api.stats.endpoints.gamerotation import GameRotation
    from nba_api.stats.endpoints.playbyplayv3 import PlayByPlayV3

    if not re.fullmatch(r"\d{10}", game_id):
        raise ValueError("Informe um ID oficial NBA de dez dígitos.")
    payloads = {
        "play_by_play": PlayByPlayV3(game_id=game_id, timeout=8).get_dict(),
        "rotations": GameRotation(game_id=game_id, timeout=8).get_dict(),
    }
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, payload in payloads.items():
        target = output / f"{game_id}_{name}.json"
        target.write_text(
            json.dumps({"fetched_at": utc_now().isoformat(), "payload": payload}), encoding="utf-8"
        )
        paths.append(target)
    return paths
