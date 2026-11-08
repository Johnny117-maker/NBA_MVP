from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .model import temporal_split_index
from .player_features import DEFAULT_REST_DAYS, EMA_HALFLIFE_SLOW
from .shot_features import THREE_POINT_ZONES, ZONE_LABELS_PT, ZONES, add_shot_value, opponent_zone_defense

# Modelo de previsão da seção 10 do planejamento: minutos → FGA já são
# resolvidos por `src/player_model/` (não repetidos aqui). Este módulo cobre
# o que falta na cadeia — distribuição por zona e eficiência por zona — e
# devolve pontos esperados de bola-de-quadra (sem lance livre: o
# `ShotChartDetail` só traz arremessos de quadra, `context_measure_simple="FGA"`).
MIN_RESIDUAL_STD_SHARE = 0.02
MIN_RESIDUAL_STD_FG_PCT = 0.03

# Mínimo de jogos-com-tentativa-na-zona para treinar um modelo de eficiência
# por zona; abaixo disso (zonas raras, ex. "Backcourt") a previsão cai na
# média da liga (`league_avg_fg_pct`) em vez de um Ridge mal ajustado.
MIN_GAMES_FOR_EFFICIENCY_MODEL = 10

# Priors fixos usados no início de cada série (primeiro jogo de um jogador ou
# de um adversário), quando ainda não há jogo anterior para formar a média.
# São valores aproximados da NBA moderna, escritos aqui e não calculados da
# base: uma média da base inteira incluiria jogos posteriores ao que está sendo
# previsto, e o valor mudaria sempre que novos jogos fossem acrescentados (o
# mesmo princípio de `DEFAULT_RATING` em `features.py`). Só afetam as
# primeiras linhas de cada série; depois disso a média móvel assume.
ZONE_SHARE_PRIOR: dict[str, float] = {
    "Restricted Area": 0.320,
    "In The Paint (Non-RA)": 0.120,
    "Mid-Range": 0.130,
    "Left Corner 3": 0.035,
    "Right Corner 3": 0.035,
    "Above the Break 3": 0.358,
    "Backcourt": 0.002,
}
ZONE_FG_PCT_PRIOR: dict[str, float] = {
    "Restricted Area": 0.650,
    "In The Paint (Non-RA)": 0.420,
    "Mid-Range": 0.410,
    "Left Corner 3": 0.390,
    "Right Corner 3": 0.390,
    "Above the Break 3": 0.360,
    "Backcourt": 0.050,
}


def split_zone_games_by_date(ordered: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa ~80% / ~20% mantendo datas completas de um lado só.

    `ordered` precisa estar ordenado por `game_date`. Vários jogadores jogam na
    mesma data; cortar por posição de linha deixaria a mesma data no treino e
    no teste. Usa o mesmo critério dos modelos de times
    (`model.py::temporal_split_index`).
    """
    split = temporal_split_index(ordered)
    return ordered.iloc[:split], ordered.iloc[split:]


def walk_forward_boundaries(dates: pd.Series, n_folds: int, min_train_games: int) -> list[int]:
    """Posições de corte do walk-forward, sem repartir uma data entre dois folds.

    Cada corte intermediário avança até o fim da data da última linha de treino,
    de modo que o treino nunca fica menor que `min_train_games`. `dates` precisa
    estar ordenado.
    """
    values = pd.to_datetime(dates).dt.normalize().to_numpy()
    total = len(values)
    raw = np.linspace(min_train_games, total, n_folds + 1, dtype=int)
    return [
        total if cut >= total else int(np.searchsorted(values, values[cut - 1], side="right"))
        for cut in raw
    ]


@dataclass
class ZoneModelBundle:
    share_models: dict[str, Pipeline]
    fg_pct_models: dict[str, Pipeline | None]
    metrics: dict[str, float]
    residual_std_share: dict[str, float]
    residual_std_fg_pct: dict[str, float]
    league_avg_share: dict[str, float]
    league_avg_fg_pct: dict[str, float]


def _regression_pipeline() -> Pipeline:
    return Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=2.0))])


def _share_features(zone: str) -> list[str]:
    return [f"share_avg10_{zone}", f"defense_share_allowed_avg_{zone}", "games_since_trade", "rest_days"]


def _efficiency_features(zone: str) -> list[str]:
    return [f"fgpct_avg10_{zone}", f"defense_fgpct_allowed_avg_{zone}", "games_since_trade", "rest_days"]


def build_zone_game_table(shots: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (jogador, jogo): tentativas/conversões por zona, em formato largo.

    Base para o resto do módulo — o pivô de `player_shots` (uma linha por
    arremesso) para o nível em que os modelos treinam (uma linha por jogo).
    """
    data = add_shot_value(shots)
    made = data["shot_made"].astype(bool)
    data["points"] = np.where(made, data["shot_value"], 0)

    keys = ["player_id", "player_name", "game_id", "game_date", "season", "team_name", "opponent"]
    totals = data.groupby(keys, as_index=False).agg(
        total_fga=("shot_attempted", "size"),
        total_fg_makes=("shot_made", "sum"),
        total_fg_points=("points", "sum"),
    )

    zone_attempts = (
        data.pivot_table(
            index=["player_id", "game_id"],
            columns="shot_zone_basic",
            values="shot_attempted",
            aggfunc="size",
            fill_value=0,
        )
        .reindex(columns=ZONES, fill_value=0)
        .add_prefix("attempts_")
    )
    zone_makes = (
        data.pivot_table(
            index=["player_id", "game_id"],
            columns="shot_zone_basic",
            values="shot_made",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(columns=ZONES, fill_value=0)
        .add_prefix("makes_")
    )

    wide = totals.merge(zone_attempts, on=["player_id", "game_id"]).merge(
        zone_makes, on=["player_id", "game_id"]
    )
    for zone in ZONES:
        wide[f"share_{zone}"] = wide[f"attempts_{zone}"] / wide["total_fga"].replace(0, np.nan)
        wide[f"share_{zone}"] = wide[f"share_{zone}"].fillna(0.0)
        wide[f"fg_pct_{zone}"] = wide[f"makes_{zone}"] / wide[f"attempts_{zone}"].replace(0, np.nan)

    wide["game_date"] = pd.to_datetime(wide["game_date"])
    return wide.sort_values(["player_id", "game_date"]).reset_index(drop=True)


def _assign_zone_team_stints(zone_games: pd.DataFrame) -> pd.DataFrame:
    """Mesmo princípio de `player_features.py::assign_team_stints`, mas sobre
    `team_name` (nome completo, como vem de `player_shots`) em vez de `team`
    (sigla, como vem de `player_game_stats`) — os dois módulos guardam o time
    em formatos diferentes (ver README)."""
    games = zone_games.sort_values(["player_id", "game_date"]).copy()
    team_changed = games.groupby("player_id")["team_name"].transform(
        lambda team: team != team.shift(1)
    )
    stint_id = team_changed.groupby(games["player_id"]).cumsum()
    games["games_since_trade"] = games.groupby([games["player_id"], stint_id]).cumcount()
    return games


def _per_player_zone_rolling(group: pd.DataFrame) -> pd.DataFrame:
    """Médias móveis exponenciais por zona, sem vazamento (`shift(1)` antes do `ewm`).

    `share_avg10_<zona>` usa todos os jogos (participação é 0 num jogo sem
    tentativa ali). `fgpct_avg10_<zona>` usa `ignore_na=True`: jogos sem
    tentativa naquela zona viram `NaN` em `fg_pct_<zona>` e são pulados no
    peso da média, em vez de contar como "0% de aproveitamento" ou quebrar o
    espaçamento temporal da EWM.
    """
    group = group.sort_values("game_date").copy()
    group["rest_days"] = (group["game_date"] - group["game_date"].shift(1)).dt.days
    for zone in ZONES:
        group[f"share_avg10_{zone}"] = (
            group[f"share_{zone}"].shift(1).ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
        )
        group[f"fgpct_avg10_{zone}"] = (
            group[f"fg_pct_{zone}"]
            .shift(1)
            .ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1, ignore_na=True)
            .mean()
        )
    return group


def add_zone_rolling_features(zone_games: pd.DataFrame) -> pd.DataFrame:
    """Adiciona `share_avg10_<zona>`/`fgpct_avg10_<zona>`/`games_since_trade`/`rest_days`.

    Tendência própria do jogador até aquele jogo (sem vazamento) — metade da
    entrada dos modelos de zona; a outra metade é a defesa do adversário
    (`add_opponent_zone_defense_features`).
    """
    games = _assign_zone_team_stints(zone_games)
    player_ids = games[["player_id"]]
    games = games.groupby("player_id", group_keys=False).apply(
        _per_player_zone_rolling, include_groups=False
    )
    games = games.join(player_ids)
    games["rest_days"] = games["rest_days"].fillna(DEFAULT_REST_DAYS).astype(int)

    for zone in ZONES:
        games[f"share_avg10_{zone}"] = games[f"share_avg10_{zone}"].fillna(ZONE_SHARE_PRIOR[zone])
        games[f"fgpct_avg10_{zone}"] = games[f"fgpct_avg10_{zone}"].fillna(ZONE_FG_PCT_PRIOR[zone])

    return games.sort_values("game_date").reset_index(drop=True)


def _team_zone_defense_games(shots: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (adversário, jogo): quanto ele permitiu em cada zona
    naquele jogo, somando todos os arremessos coletados contra ele (podem ser
    de vários jogadores diferentes) — insumo da defesa por zona (seção 9)."""
    data = add_shot_value(shots)

    totals = data.groupby(["opponent", "game_id", "game_date"], as_index=False).agg(
        total_fga=("shot_attempted", "size"),
    )
    zone_attempts = (
        data.pivot_table(
            index=["opponent", "game_id"],
            columns="shot_zone_basic",
            values="shot_attempted",
            aggfunc="size",
            fill_value=0,
        )
        .reindex(columns=ZONES, fill_value=0)
        .add_prefix("attempts_")
    )
    zone_makes = (
        data.pivot_table(
            index=["opponent", "game_id"],
            columns="shot_zone_basic",
            values="shot_made",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(columns=ZONES, fill_value=0)
        .add_prefix("makes_")
    )

    merged = totals.merge(zone_attempts, on=["opponent", "game_id"]).merge(
        zone_makes, on=["opponent", "game_id"]
    )
    for zone in ZONES:
        merged[f"share_allowed_{zone}"] = merged[f"attempts_{zone}"] / merged["total_fga"].replace(
            0, np.nan
        )
        merged[f"share_allowed_{zone}"] = merged[f"share_allowed_{zone}"].fillna(0.0)
        merged[f"fg_pct_allowed_{zone}"] = merged[f"makes_{zone}"] / merged[f"attempts_{zone}"].replace(
            0, np.nan
        )

    merged["game_date"] = pd.to_datetime(merged["game_date"])
    return merged.sort_values(["opponent", "game_date"]).reset_index(drop=True)


def _expanding_zone_defense(group: pd.DataFrame) -> pd.DataFrame:
    """Média expansiva (não EWMA) de quanto o time permitiu por zona, só com
    jogos anteriores — mesmo raciocínio de
    `player_features.py::_expanding_defense` (`opponent_def_rating`): a
    tendência defensiva de um time por zona muda pouco de uma semana para
    outra, então uma janela curta seria mais ruído do que sinal."""
    group = group.sort_values("game_date").copy()
    for zone in ZONES:
        group[f"defense_share_allowed_avg_{zone}"] = (
            group[f"share_allowed_{zone}"].shift(1).expanding(min_periods=1).mean()
        )
        group[f"defense_fgpct_allowed_avg_{zone}"] = (
            group[f"fg_pct_allowed_{zone}"]
            .shift(1)
            .expanding(min_periods=1)
            .mean()
        )
    return group


def add_opponent_zone_defense_features(zone_games: pd.DataFrame, shots: pd.DataFrame) -> pd.DataFrame:
    """Adiciona `defense_share_allowed_avg_<zona>`/`defense_fgpct_allowed_avg_<zona>`:
    quanto o adversário daquele jogo costumava permitir por zona até essa data
    (sem vazamento). `player_shots.opponent`/`.team_name` já usam o mesmo
    formato de nome completo dos dois lados (ao contrário de
    `player_game_stats`, que mistura sigla e nome — ver README), então o
    `merge_asof` não precisa de nenhuma tradução extra.
    """
    defense_games = _team_zone_defense_games(shots)
    opponent_column = defense_games[["opponent"]]
    defense_games = defense_games.groupby("opponent", group_keys=False).apply(
        _expanding_zone_defense, include_groups=False
    )
    defense_games = defense_games.join(opponent_column)

    defense_feature_columns = [
        f"defense_{kind}_avg_{zone}" for zone in ZONES for kind in ("share_allowed", "fgpct_allowed")
    ]
    defense_lookup = (
        defense_games[["opponent", "game_date", *defense_feature_columns]]
        .sort_values("game_date")
        .reset_index(drop=True)
    )

    merged = pd.merge_asof(
        zone_games.sort_values("game_date").reset_index(drop=True),
        defense_lookup,
        on="game_date",
        by="opponent",
        direction="backward",
    )
    for zone in ZONES:
        merged[f"defense_share_allowed_avg_{zone}"] = merged[
            f"defense_share_allowed_avg_{zone}"
        ].fillna(ZONE_SHARE_PRIOR[zone])
        merged[f"defense_fgpct_allowed_avg_{zone}"] = merged[
            f"defense_fgpct_allowed_avg_{zone}"
        ].fillna(ZONE_FG_PCT_PRIOR[zone])
    return merged.sort_values("game_date").reset_index(drop=True)


def add_zone_model_features(shots: pd.DataFrame) -> pd.DataFrame:
    """Atalho: `build_zone_game_table` + as duas rodadas de features (própria
    tendência e defesa do adversário), na ordem certa."""
    zone_games = build_zone_game_table(shots)
    zone_games = add_zone_rolling_features(zone_games)
    return add_opponent_zone_defense_features(zone_games, shots)


def train_zone_models(zone_games_with_features: pd.DataFrame) -> ZoneModelBundle:
    """Treina os modelos de zona: um Ridge de participação (`share`) e um Ridge
    de eficiência (`fg_pct`) por zona, igual em espírito aos modelos de
    `player_model/` (regressão sobre a taxa agregada, não classificação por
    arremesso individual — mesma escolha já feita para TS%/per-36 no resto do
    projeto). Um único treino usa os jogos de **todos** os jogadores já
    coletados (não um modelo por jogador) — mesma arquitetura de
    `train_player_models`, generaliza melhor conforme mais jogadores entram
    na base.
    """
    if len(zone_games_with_features) < 30:
        raise ValueError(
            "São necessários pelo menos 30 jogos (de qualquer jogador) para treinar "
            "os modelos de zona."
        )

    ordered = zone_games_with_features.sort_values("game_date").reset_index(drop=True)
    train_rows, test_rows = split_zone_games_by_date(ordered)

    share_models_eval: dict[str, Pipeline] = {}
    fg_pct_models_eval: dict[str, Pipeline | None] = {}
    metrics: dict[str, float] = {}
    residual_std_share: dict[str, float] = {}
    residual_std_fg_pct: dict[str, float] = {}

    for zone in ZONES:
        share_features = _share_features(zone)
        share_model = _regression_pipeline().fit(train_rows[share_features], train_rows[f"share_{zone}"])
        predicted_share = np.maximum(0.0, share_model.predict(test_rows[share_features]))
        metrics[f"share_mae_{zone}"] = float(
            mean_absolute_error(test_rows[f"share_{zone}"], predicted_share)
        )
        residual_std_share[zone] = max(
            float(np.std(test_rows[f"share_{zone}"].to_numpy() - predicted_share)),
            MIN_RESIDUAL_STD_SHARE,
        )
        share_models_eval[zone] = share_model

        eff_features = _efficiency_features(zone)
        train_eff = train_rows[train_rows[f"attempts_{zone}"] > 0]
        test_eff = test_rows[test_rows[f"attempts_{zone}"] > 0]
        if len(train_eff) >= MIN_GAMES_FOR_EFFICIENCY_MODEL and len(test_eff) >= 5:
            fg_pct_model = _regression_pipeline().fit(train_eff[eff_features], train_eff[f"fg_pct_{zone}"])
            predicted_fg_pct = np.clip(fg_pct_model.predict(test_eff[eff_features]), 0.0, 1.0)
            metrics[f"fg_pct_mae_{zone}"] = float(
                mean_absolute_error(test_eff[f"fg_pct_{zone}"], predicted_fg_pct)
            )
            residual_std_fg_pct[zone] = max(
                float(np.std(test_eff[f"fg_pct_{zone}"].to_numpy() - predicted_fg_pct)),
                MIN_RESIDUAL_STD_FG_PCT,
            )
            fg_pct_models_eval[zone] = fg_pct_model
        else:
            fg_pct_models_eval[zone] = None
            residual_std_fg_pct[zone] = MIN_RESIDUAL_STD_FG_PCT

    league_avg_share = {zone: float(ordered[f"share_{zone}"].mean()) for zone in ZONES}
    league_avg_fg_pct = {}
    for zone in ZONES:
        qualified = ordered[ordered[f"attempts_{zone}"] > 0]
        league_avg_fg_pct[zone] = float(qualified[f"fg_pct_{zone}"].mean()) if not qualified.empty else 0.0

    final_share_models = {
        zone: clone(share_models_eval[zone]).fit(ordered[_share_features(zone)], ordered[f"share_{zone}"])
        for zone in ZONES
    }
    final_fg_pct_models: dict[str, Pipeline | None] = {}
    for zone in ZONES:
        all_eff = ordered[ordered[f"attempts_{zone}"] > 0]
        if fg_pct_models_eval[zone] is not None and len(all_eff) >= MIN_GAMES_FOR_EFFICIENCY_MODEL:
            final_fg_pct_models[zone] = clone(fg_pct_models_eval[zone]).fit(
                all_eff[_efficiency_features(zone)], all_eff[f"fg_pct_{zone}"]
            )
        else:
            final_fg_pct_models[zone] = None

    return ZoneModelBundle(
        share_models=final_share_models,
        fg_pct_models=final_fg_pct_models,
        metrics=metrics,
        residual_std_share=residual_std_share,
        residual_std_fg_pct=residual_std_fg_pct,
        league_avg_share=league_avg_share,
        league_avg_fg_pct=league_avg_fg_pct,
    )


def predict_zone_distribution(bundle: ZoneModelBundle, rows: pd.DataFrame) -> pd.DataFrame:
    """Previsão por zona (participação normalizada de FGA + FG% esperado), em lote.

    `rows` precisa trazer as features de `add_zone_model_features` (treino/
    avaliação) ou de `live_zone_snapshot` (previsão de um jogo futuro).
    Devolve formato longo — uma linha por (`row_index`, zona) — para caber
    tanto uma única previsão ao vivo quanto um lote inteiro de walk-forward
    numa só chamada.
    """
    raw_shares: dict[str, np.ndarray] = {}
    predicted_fg_pcts: dict[str, np.ndarray] = {}
    for zone in ZONES:
        share_features = _share_features(zone)
        raw_shares[zone] = np.maximum(0.0, bundle.share_models[zone].predict(rows[share_features]))

        fg_pct_model = bundle.fg_pct_models[zone]
        if fg_pct_model is not None:
            predicted_fg_pcts[zone] = np.clip(
                fg_pct_model.predict(rows[_efficiency_features(zone)]), 0.0, 1.0
            )
        else:
            predicted_fg_pcts[zone] = np.full(len(rows), bundle.league_avg_fg_pct[zone])

    share_matrix = np.column_stack([raw_shares[zone] for zone in ZONES])
    totals = share_matrix.sum(axis=1)
    totals_safe = np.where(totals > 0, totals, 1.0)
    normalized = np.where(
        totals[:, None] > 0, share_matrix / totals_safe[:, None], 1.0 / len(ZONES)
    )

    frames = []
    for i, zone in enumerate(ZONES):
        frames.append(
            pd.DataFrame(
                {
                    "row_index": rows.index,
                    "shot_zone_basic": zone,
                    "zone_label": ZONE_LABELS_PT.get(zone, zone),
                    "predicted_share": normalized[:, i],
                    "predicted_fg_pct": predicted_fg_pcts[zone],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def expected_fg_points(zone_predictions: pd.DataFrame, predicted_fga: pd.Series) -> pd.Series:
    """Combina distribuição por zona + FGA previstos em pontos esperados de
    bola-de-quadra, por linha original — o "Pontos totais" (só campo) do
    diagrama da seção 10. `predicted_fga` precisa ter o mesmo índice usado em
    `predict_zone_distribution` (a coluna `row_index` do resultado). Lance
    livre fica fora daqui: combine com `player_model/prediction.py::predict_player_game`
    (FTA × aproveitamento de lance livre do jogador) para o total do jogo.
    """
    data = zone_predictions.copy()
    data["predicted_fga_zone"] = data["predicted_share"] * data["row_index"].map(predicted_fga)
    data["shot_value"] = np.where(data["shot_zone_basic"].isin(THREE_POINT_ZONES), 3, 2)
    data["predicted_points_zone"] = (
        data["predicted_fga_zone"] * data["predicted_fg_pct"] * data["shot_value"]
    )
    return data.groupby("row_index")["predicted_points_zone"].sum().rename("predicted_fg_points")


def opponent_zone_defense_snapshot(shots: pd.DataFrame, defending_team: str) -> dict[str, float]:
    """Estado atual (todos os arremessos já coletados, sem corte de data) da
    defesa por zona de um adversário — para prever um jogo genuinamente
    futuro. Diferente de `add_opponent_zone_defense_features` (que usa média
    expansiva sem vazamento, para treino/avaliação): aqui não há "vazamento"
    a evitar, é literalmente o estado mais atual que a base tem.
    """
    defense = opponent_zone_defense(shots)
    team_rows = defense[defense["defending_team"] == defending_team].set_index("shot_zone_basic")
    total_attempts = float(team_rows["attempts_against"].sum()) if not team_rows.empty else 0.0

    snapshot: dict[str, float] = {}
    for zone in ZONES:
        if zone in team_rows.index and total_attempts > 0:
            snapshot[f"defense_share_allowed_avg_{zone}"] = float(
                team_rows.loc[zone, "attempts_against"] / total_attempts
            )
            snapshot[f"defense_fgpct_allowed_avg_{zone}"] = float(team_rows.loc[zone, "fg_pct_against"])
        else:
            snapshot[f"defense_share_allowed_avg_{zone}"] = float("nan")
            snapshot[f"defense_fgpct_allowed_avg_{zone}"] = float("nan")
    return snapshot


def live_zone_snapshot(
    zone_games_with_features: pd.DataFrame,
    player_id: int,
    defending_team: str | None,
    shots: pd.DataFrame,
    rest_days: int = DEFAULT_REST_DAYS,
) -> pd.DataFrame:
    """Estado atual (sem `shift`) de um jogador para prever um jogo futuro —
    mesmo princípio de `player_metrics.py::player_snapshot`: recalcula a EWMA
    incluindo o último jogo já disputado, em vez de usar a versão "defasada
    em um jogo" que o treino usa (lá o `shift(1)` existe para não vazar o
    resultado do próprio jogo que está sendo previsto; aqui não existe esse
    risco, o jogo que queremos prever ainda não aconteceu).
    """
    player_rows = zone_games_with_features[
        zone_games_with_features["player_id"] == player_id
    ].sort_values("game_date")
    if player_rows.empty:
        raise ValueError(f"Nenhum arremesso coletado para o jogador {player_id}.")

    latest = player_rows.iloc[-1]
    features: dict[str, float] = {
        "games_since_trade": float(latest["games_since_trade"]),
        "rest_days": float(rest_days),
    }

    defense_snapshot = (
        opponent_zone_defense_snapshot(shots, defending_team) if defending_team else {}
    )

    for zone in ZONES:
        share_series = player_rows[f"share_{zone}"].ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
        features[f"share_avg10_{zone}"] = float(share_series.iloc[-1])

        eff_rows = player_rows[player_rows[f"attempts_{zone}"] > 0]
        if not eff_rows.empty:
            fgpct_series = eff_rows[f"fg_pct_{zone}"].ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
            features[f"fgpct_avg10_{zone}"] = float(fgpct_series.iloc[-1])
        else:
            features[f"fgpct_avg10_{zone}"] = float("nan")

        defense_share = defense_snapshot.get(f"defense_share_allowed_avg_{zone}", float("nan"))
        defense_fg_pct = defense_snapshot.get(f"defense_fgpct_allowed_avg_{zone}", float("nan"))
        features[f"defense_share_allowed_avg_{zone}"] = defense_share
        features[f"defense_fgpct_allowed_avg_{zone}"] = defense_fg_pct

    return pd.DataFrame([features])


def fill_missing_features_with_league_average(bundle: ZoneModelBundle, row: pd.DataFrame) -> pd.DataFrame:
    """Substitui `NaN` (zona nunca vista pelo jogador, ou adversário sem
    amostra numa zona) pela média da liga guardada no bundle — os modelos
    (`StandardScaler` + `Ridge`) não aceitam `NaN` na entrada."""
    filled = row.copy()
    for zone in ZONES:
        filled[f"share_avg10_{zone}"] = filled[f"share_avg10_{zone}"].fillna(
            bundle.league_avg_share[zone]
        )
        filled[f"fgpct_avg10_{zone}"] = filled[f"fgpct_avg10_{zone}"].fillna(
            bundle.league_avg_fg_pct[zone]
        )
        filled[f"defense_share_allowed_avg_{zone}"] = filled[
            f"defense_share_allowed_avg_{zone}"
        ].fillna(bundle.league_avg_share[zone])
        filled[f"defense_fgpct_allowed_avg_{zone}"] = filled[
            f"defense_fgpct_allowed_avg_{zone}"
        ].fillna(bundle.league_avg_fg_pct[zone])
    return filled


def walk_forward_evaluate_zone_models(
    zone_games_with_features: pd.DataFrame, n_folds: int = 5, min_train_games: int = 30
) -> dict:
    """Validação walk-forward dos modelos de zona (seção 17 do planejamento):
    treina até uma data, avalia no pedaço seguinte, avança — mesmo princípio
    de `player_model/evaluation.py::walk_forward_evaluate`.

    Usa o **FGA real** de cada jogo do teste (não uma previsão) para calcular
    `fg_points_mae`: isola o erro da decomposição por zona do erro do modelo
    de volume de arremessos, que já é validado separadamente em
    `player_model/`. Reporta também o MAE de participação (`share`) por
    zona, fold a fold.
    """
    ordered = zone_games_with_features.sort_values("game_date").reset_index(drop=True)
    if len(ordered) < min_train_games * 2:
        raise ValueError(
            f"São necessários pelo menos {min_train_games * 2} jogos (de qualquer "
            "jogador) para validação walk-forward dos modelos de zona."
        )

    boundaries = walk_forward_boundaries(ordered["game_date"], n_folds, min_train_games)
    fold_results = []

    for fold_index in range(n_folds):
        train_end = boundaries[fold_index]
        test_end = boundaries[fold_index + 1]
        if test_end <= train_end:
            continue
        train_fold = ordered.iloc[:train_end]
        test_fold = ordered.iloc[train_end:test_end]
        if test_fold.empty:
            continue

        bundle = train_zone_models(train_fold)
        zone_predictions = predict_zone_distribution(bundle, test_fold)
        predicted_points = expected_fg_points(zone_predictions, test_fold["total_fga"])

        fold_metrics = {
            "fold": fold_index,
            "n_train": int(train_end),
            "n_test": int(len(test_fold)),
            "fg_points_mae": float(
                mean_absolute_error(test_fold["total_fg_points"], predicted_points.reindex(test_fold.index))
            ),
        }
        for zone in ZONES:
            share_features = _share_features(zone)
            predicted_share = np.maximum(0.0, bundle.share_models[zone].predict(test_fold[share_features]))
            fold_metrics[f"share_mae_{zone}"] = float(
                mean_absolute_error(test_fold[f"share_{zone}"], predicted_share)
            )
        fold_results.append(fold_metrics)

    if not fold_results:
        raise ValueError("Não foi possível formar nenhum fold de validação walk-forward.")

    aggregate = {"fg_points_mae": float(np.mean([fold["fg_points_mae"] for fold in fold_results]))}
    for zone in ZONES:
        aggregate[f"share_mae_{zone}"] = float(
            np.mean([fold[f"share_mae_{zone}"] for fold in fold_results])
        )
    aggregate["n_folds"] = len(fold_results)
    return {"folds": fold_results, "aggregate": aggregate}
