from __future__ import annotations

import numpy as np
import pandas as pd

# Tradução dos SHOT_ZONE_BASIC da nba_api (seção 3.4 do planejamento).
ZONE_LABELS_PT: dict[str, str] = {
    "Restricted Area": "Aro",
    "In The Paint (Non-RA)": "Garrafão",
    "Mid-Range": "Meia distância",
    "Left Corner 3": "Canto esquerdo de três",
    "Right Corner 3": "Canto direito de três",
    "Above the Break 3": "Três frontal",
    "Backcourt": "Arremesso muito longo",
}

THREE_POINT_ZONES = {"Left Corner 3", "Right Corner 3", "Above the Break 3", "Backcourt"}
MIDRANGE_ZONES = {"Mid-Range"}

# Lista canônica e ordenada das zonas — mesma ordem de `ZONE_LABELS_PT`,
# reaproveitada por `src/shot_model/` para nomear colunas de feature por zona.
ZONES = list(ZONE_LABELS_PT)

_ZONE_SUMMARY_COLUMNS = [
    "shot_zone_basic",
    "zone_label",
    "attempts",
    "makes",
    "points",
    "avg_distance",
    "fg_pct",
    "frequency",
    "points_per_shot",
]

# Peso do "prior" (média da liga) na suavização bayesiana do FG% por zona —
# quanto maior, mais uma amostra pequena puxa para a média da liga em vez do
# valor observado (seção 6 do planejamento: 3 de 4 não é 75% de verdade).
SHRINKAGE_PRIOR_ATTEMPTS = 20

# Mínimo de tentativas para uma zona concorrer a "mais eficiente"/"maior diferença" —
# evita eleger uma zona de 1 arremesso convertido como destaque.
MIN_ATTEMPTS_FOR_RANKING = 5


def add_shot_value(shots: pd.DataFrame) -> pd.DataFrame:
    """Adiciona `shot_value` (2 ou 3 pontos) a partir de `shot_type`."""
    data = shots.copy()
    data["shot_value"] = np.where(data["shot_type"].str.startswith("3PT"), 3, 2)
    return data


def zone_summary(shots: pd.DataFrame) -> pd.DataFrame:
    """Agrupa arremessos por zona: volume, eficiência e pontos por tentativa.

    Frequência (volume) e FG%/pontos por tentativa (eficiência) ficam em
    colunas separadas — seção 4 do planejamento pede que as duas nunca sejam
    misturadas numa taxa só, para não confundir "atira muito daqui" com
    "converte bem daqui".
    """
    if shots.empty:
        return pd.DataFrame(columns=_ZONE_SUMMARY_COLUMNS)

    data = add_shot_value(shots)
    made = data["shot_made"].astype(bool)
    data["points"] = np.where(made, data["shot_value"], 0)

    total_attempts = len(data)
    grouped = data.groupby("shot_zone_basic", as_index=False).agg(
        attempts=("shot_attempted", "size"),
        makes=("shot_made", "sum"),
        points=("points", "sum"),
        avg_distance=("shot_distance", "mean"),
    )
    grouped["makes"] = grouped["makes"].astype(int)
    grouped["fg_pct"] = grouped["makes"] / grouped["attempts"]
    grouped["frequency"] = grouped["attempts"] / total_attempts
    grouped["points_per_shot"] = grouped["points"] / grouped["attempts"]
    grouped["zone_label"] = grouped["shot_zone_basic"].map(ZONE_LABELS_PT).fillna(
        grouped["shot_zone_basic"]
    )

    return grouped[_ZONE_SUMMARY_COLUMNS].sort_values("attempts", ascending=False).reset_index(
        drop=True
    )


def league_zone_rates(shots: pd.DataFrame) -> pd.DataFrame:
    """FG% e pontos/tentativa por zona numa base de referência.

    `shots` deve ser a amostra usada como "liga" (ex.: todos os arremessos já
    coletados, ou uma temporada inteira) — quem chama decide o que conta como
    referência.
    """
    summary = zone_summary(shots)
    return summary[["shot_zone_basic", "fg_pct", "points_per_shot"]].rename(
        columns={"fg_pct": "league_fg_pct", "points_per_shot": "league_points_per_shot"}
    )


def compare_to_league(player_summary: pd.DataFrame, league_rates: pd.DataFrame) -> pd.DataFrame:
    """Cruza o resumo por zona de um jogador com a referência da liga.

    Adiciona `shrunk_fg_pct`: suavização bayesiana simples que puxa o FG%
    observado em direção à média da liga na proporção inversa do volume de
    tentativas (`SHRINKAGE_PRIOR_ATTEMPTS`) — protege contra amostra pequena
    (seção 6 do planejamento) sem esconder o valor bruto (`fg_pct` continua
    disponível ao lado).
    """
    merged = player_summary.merge(
        league_rates, on="shot_zone_basic", how="left", suffixes=("", "_league")
    )
    # Zona sem nenhuma referência de liga (ex.: liga vazia): não suaviza, mantém o valor observado.
    merged["league_fg_pct"] = merged["league_fg_pct"].fillna(merged["fg_pct"])
    merged["league_points_per_shot"] = merged["league_points_per_shot"].fillna(
        merged["points_per_shot"]
    )

    k = SHRINKAGE_PRIOR_ATTEMPTS
    merged["shrunk_fg_pct"] = (merged["makes"] + merged["league_fg_pct"] * k) / (
        merged["attempts"] + k
    )
    merged["diff_fg_pct"] = merged["fg_pct"] - merged["league_fg_pct"]
    merged["diff_points_per_shot"] = merged["points_per_shot"] - merged["league_points_per_shot"]
    return merged


def filter_shots(
    shots: pd.DataFrame,
    season: str | None = None,
    team_name: str | None = None,
    opponent: str | None = None,
    date_from: pd.Timestamp | str | None = None,
    date_to: pd.Timestamp | str | None = None,
    period: int | None = None,
    shot_zone_basic: str | None = None,
    made_only: bool | None = None,
    first_n_games: int | None = None,
    last_n_games: int | None = None,
) -> pd.DataFrame:
    """Aplica os segmentadores mais comuns (seções 7 e 13 do planejamento).

    Filtros simples sobre colunas que já existem em `player_shots` — mesmo
    espírito dos filtros de período/adversário já usados na página de
    jogadores (`pages/1_Jogadores.py`), sem precisar de nenhuma coleta nova.
    `first_n_games`/`last_n_games` habilitam a comparação "primeiros N ×
    últimos N jogos" da seção 7. Casa/fora, passagem por time e temporada
    regular/playoffs ainda não são suportados aqui: `player_shots` não guarda
    mando de quadra nem tipo de temporada nesta primeira versão.
    """
    data = shots
    if season is not None:
        data = data[data["season"] == season]
    if team_name is not None:
        data = data[data["team_name"] == team_name]
    if opponent is not None:
        data = data[data["opponent"] == opponent]
    if date_from is not None:
        data = data[data["game_date"] >= pd.Timestamp(date_from)]
    if date_to is not None:
        data = data[data["game_date"] <= pd.Timestamp(date_to)]
    if period is not None:
        data = data[data["period"] == period]
    if shot_zone_basic is not None:
        data = data[data["shot_zone_basic"] == shot_zone_basic]
    if made_only is not None:
        data = data[data["shot_made"].astype(bool) == made_only]
    if first_n_games is not None:
        earliest_games = (
            data[["game_id", "game_date"]]
            .drop_duplicates()
            .sort_values("game_date")
            .head(first_n_games)["game_id"]
        )
        data = data[data["game_id"].isin(earliest_games)]
    if last_n_games is not None:
        recent_games = (
            data[["game_id", "game_date"]]
            .drop_duplicates()
            .sort_values("game_date")
            .tail(last_n_games)["game_id"]
        )
        data = data[data["game_id"].isin(recent_games)]
    return data.reset_index(drop=True)


def shot_indicators(
    shots: pd.DataFrame, league_rates: pd.DataFrame | None = None
) -> dict[str, object]:
    """Indicadores gerais de um recorte de arremessos (seção 14 do planejamento)."""
    if shots.empty:
        return {}

    data = add_shot_value(shots)
    made = data["shot_made"].astype(bool)
    total_attempts = len(data)
    total_makes = int(made.sum())
    three_makes = int((made & (data["shot_value"] == 3)).sum())
    total_points = int((made * data["shot_value"]).sum())

    summary = zone_summary(shots)
    qualified = summary[summary["attempts"] >= MIN_ATTEMPTS_FOR_RANKING]

    indicators: dict[str, object] = {
        "total_attempts": total_attempts,
        "total_makes": total_makes,
        "fg_pct": total_makes / total_attempts,
        "efg_pct": (total_makes + 0.5 * three_makes) / total_attempts,
        "points_per_shot": total_points / total_attempts,
        "avg_distance": float(data["shot_distance"].mean()),
        "pct_rim": float(
            summary.loc[summary["shot_zone_basic"] == "Restricted Area", "frequency"].sum()
        ),
        "pct_three": float(
            summary.loc[summary["shot_zone_basic"].isin(THREE_POINT_ZONES), "frequency"].sum()
        ),
        "pct_midrange": float(
            summary.loc[summary["shot_zone_basic"].isin(MIDRANGE_ZONES), "frequency"].sum()
        ),
        "most_used_zone": summary.iloc[0]["zone_label"],
        "most_efficient_zone": (
            qualified.sort_values("points_per_shot", ascending=False).iloc[0]["zone_label"]
            if not qualified.empty
            else None
        ),
        "best_diff_zone": None,
        "best_diff_points_per_shot": None,
        "volume_low_efficiency_zone": None,
    }

    if league_rates is not None:
        compared = compare_to_league(summary, league_rates)
        compared_qualified = compared[compared["attempts"] >= MIN_ATTEMPTS_FOR_RANKING]
        if not compared_qualified.empty:
            best_diff = compared_qualified.sort_values(
                "diff_points_per_shot", ascending=False
            ).iloc[0]
            indicators["best_diff_zone"] = best_diff["zone_label"]
            indicators["best_diff_points_per_shot"] = float(best_diff["diff_points_per_shot"])

            volume_threshold = compared_qualified["attempts"].median()
            low_efficiency = compared_qualified[
                (compared_qualified["attempts"] >= volume_threshold)
                & (compared_qualified["diff_points_per_shot"] < 0)
            ].sort_values("attempts", ascending=False)
            if not low_efficiency.empty:
                indicators["volume_low_efficiency_zone"] = low_efficiency.iloc[0]["zone_label"]

    return indicators


def compare_periods(shots_a: pd.DataFrame, shots_b: pd.DataFrame) -> pd.DataFrame:
    """Tabela comparativa por zona entre dois recortes (seção 7 do planejamento).

    `shots_a`/`shots_b` já devem vir filtrados (ex.: por `filter_shots`) para o
    que se quer comparar — temporada anterior × atual, time anterior × atual,
    primeiros N jogos × últimos N, etc. Uma linha por zona presente em pelo
    menos um dos dois lados; zona ausente de um lado entra com volume zero.
    """
    summary_a = zone_summary(shots_a).set_index("shot_zone_basic")
    summary_b = zone_summary(shots_b).set_index("shot_zone_basic")
    zones = sorted(set(summary_a.index) | set(summary_b.index))

    rows = []
    for zone in zones:
        row_a = summary_a.loc[zone] if zone in summary_a.index else None
        row_b = summary_b.loc[zone] if zone in summary_b.index else None
        rows.append(
            {
                "shot_zone_basic": zone,
                "zone_label": ZONE_LABELS_PT.get(zone, zone),
                "attempts_a": int(row_a["attempts"]) if row_a is not None else 0,
                "attempts_b": int(row_b["attempts"]) if row_b is not None else 0,
                "frequency_a": float(row_a["frequency"]) if row_a is not None else 0.0,
                "frequency_b": float(row_b["frequency"]) if row_b is not None else 0.0,
                "fg_pct_a": float(row_a["fg_pct"]) if row_a is not None else np.nan,
                "fg_pct_b": float(row_b["fg_pct"]) if row_b is not None else np.nan,
                "points_per_shot_a": float(row_a["points_per_shot"]) if row_a is not None else np.nan,
                "points_per_shot_b": float(row_b["points_per_shot"]) if row_b is not None else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["attempts_a", "attempts_b"], ascending=False
    ).reset_index(drop=True)


_OPPONENT_DEFENSE_COLUMNS = [
    "defending_team",
    "shot_zone_basic",
    "zone_label",
    "attempts_against",
    "makes_against",
    "points_against",
    "fg_pct_against",
    "points_per_shot_against",
]


def opponent_zone_defense(shots: pd.DataFrame) -> pd.DataFrame:
    """FG% e pontos/tentativa permitidos por zona, por time defensor (seção 9).

    Deriva de `player_shots.opponent` (quem defendeu cada arremesso) — vira
    uma visão calculada em vez de uma tabela nova no banco (o
    `opponent_zone_defense` da seção 11 do planejamento). A amostra é limitada
    aos jogadores já coletados nesta base, não a liga inteira: quanto mais
    jogadores forem coletados, mais confiável fica o perfil defensivo de cada
    time.
    """
    if shots.empty:
        return pd.DataFrame(columns=_OPPONENT_DEFENSE_COLUMNS)

    data = add_shot_value(shots)
    made = data["shot_made"].astype(bool)
    data["points"] = np.where(made, data["shot_value"], 0)

    grouped = data.groupby(["opponent", "shot_zone_basic"], as_index=False).agg(
        attempts_against=("shot_attempted", "size"),
        makes_against=("shot_made", "sum"),
        points_against=("points", "sum"),
    )
    grouped["makes_against"] = grouped["makes_against"].astype(int)
    grouped["fg_pct_against"] = grouped["makes_against"] / grouped["attempts_against"]
    grouped["points_per_shot_against"] = grouped["points_against"] / grouped["attempts_against"]
    grouped["zone_label"] = grouped["shot_zone_basic"].map(ZONE_LABELS_PT).fillna(
        grouped["shot_zone_basic"]
    )
    grouped = grouped.rename(columns={"opponent": "defending_team"})
    return grouped[_OPPONENT_DEFENSE_COLUMNS]


def compare_to_opponent_defense(
    player_summary: pd.DataFrame, opponent_defense: pd.DataFrame, defending_team: str
) -> pd.DataFrame:
    """Cruza o perfil ofensivo por zona do jogador com o que um adversário permite.

    `opponent_defense` é o retorno de `opponent_zone_defense` já calculado
    para a base inteira; aqui filtra só o `defending_team` escolhido. Mesma
    ideia de `compare_to_league`, mas usando um adversário específico como
    referência em vez da liga inteira — responde "como esse adversário deve
    influenciar a distribuição de arremessos?" (seção 9 do planejamento).
    Zona sem nenhum arremesso registrado contra esse adversário fica com as
    colunas `_against` vazias (`NaN`), não zero — significa "sem amostra
    ainda", não "adversário impenetrável nessa zona".
    """
    defense_rows = opponent_defense.loc[
        opponent_defense["defending_team"] == defending_team,
        ["shot_zone_basic", "attempts_against", "fg_pct_against", "points_per_shot_against"],
    ]
    merged = player_summary.merge(defense_rows, on="shot_zone_basic", how="left")
    merged["diff_points_per_shot_vs_opponent"] = (
        merged["points_per_shot"] - merged["points_per_shot_against"]
    )
    return merged
