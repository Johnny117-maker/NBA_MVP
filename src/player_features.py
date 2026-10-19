from __future__ import annotations

import numpy as np
import pandas as pd

from .nba_teams import TEAM_ABBREVIATION_TO_NAME

DEFAULT_REST_DAYS = 3
# Meia-vida do peso exponencial: quantos jogos atrás um jogo tem metade do
# peso do jogo mais recente. "Rápida" reage a uma sequência quente/fria em
# poucos jogos; "lenta" ~= o exemplo do próprio planejamento ("cinco jogos
# atrás: peso intermediário"). Substitui a antiga janela flat (rolling(N)),
# que tratava o jogo mais recente e o jogo N partidas atrás com peso igual.
EMA_HALFLIFE_FAST = 2
EMA_HALFLIFE_SLOW = 5

# "fga"/"fta" entram aqui para dar o volume de arremessos (tentativas por
# minuto) usado pela decomposição volume × eficiência dos pontos; "pts" segue
# calculado para os jogadores/testes que ainda usam a taxa direta.
PER_MIN_STATS = ("pts", "reb", "ast", "fga", "fta")

RECENT_WINDOWS = (3, 5, 10)
SHORT_WINDOWS = (3, 5)

# Priors neutros usados apenas quando ainda não existe histórico anterior à
# primeira data da base. Não são calculados com dados futuros.
INITIAL_PRIORS = {
    "minutes": 18.0,
    "pts": 9.0,
    "pts_per_min": 0.50,
    "reb_per_min": 0.22,
    "ast_per_min": 0.14,
    "fga_per_min": 0.40,
    "fta_per_min": 0.11,
    "true_shooting_pct": 0.52,
    "usage_pct": 20.0,
    "starter_rate": 0.20,
}

STINT_COLUMNS = [
    "minutes_avg5_stint",
    "minutes_avg10_stint",
    *(f"{stat}_per_min_avg10_stint" for stat in PER_MIN_STATS),
    *(f"{stat}_per_min_avg{window}_stint" for stat in PER_MIN_STATS for window in SHORT_WINDOWS),
    *(f"{stat}_avg{window}_stint" for stat in ("pts",) for window in SHORT_WINDOWS),
    "ts_pct_avg10_stint",
    *(f"ts_pct_avg{window}_stint" for window in SHORT_WINDOWS),
    "usg_pct_avg10_stint",
    "usg_pct_avg5_stint",
    "starter_rate_avg10_stint",
]


def effective_starter_flag(player_games: pd.DataFrame) -> pd.Series:
    """Titularidade (titular/reserva) de cada linha, real quando coletada, ou
    aproximada quando ainda não (`scripts/update_starter_status.py` — uma
    chamada por jogo, coleta incremental e lenta, igual ao Rating oficial).

    A aproximação é "jogou mais minutos que a mediana do time naquele jogo"
    — mesmo espírito da aproximação por pontos usada para o Rating oficial
    antes da coleta chegar: nada quebra por titularidade ausente, só fica
    menos preciso até a coleta avançar.
    """
    team_game_median_minutes = player_games.groupby(["game_id", "team"])["minutes"].transform(
        "median"
    )
    approx = player_games["minutes"] > team_game_median_minutes
    if "is_starter" in player_games.columns:
        real = player_games["is_starter"]
        return real.where(real.notna(), approx).astype(bool)
    return approx


def assign_team_stints(player_games: pd.DataFrame) -> pd.DataFrame:
    """Marca cada jogo com a passagem (stint) do jogador pelo time daquele jogo.

    Uma passagem é uma sequência de jogos consecutivos (por data) do jogador
    pelo mesmo time. Detecta troca de time comparando com o jogo anterior do
    mesmo jogador — não precisa de nenhuma coleta ou tabela nova, é derivável
    inteiramente da coluna `team` que já existe em `player_game_stats`.

    Devolve `player_games` ordenado por (player_id, game_date), com duas
    colunas novas: `team_stint_id` (identifica a passagem dentro de cada
    jogador) e `games_since_trade` (0 no primeiro jogo de cada passagem).
    """
    games = player_games.copy()
    games["game_date"] = pd.to_datetime(games["game_date"])
    games = games.sort_values(["player_id", "game_date"])

    team_changed = games.groupby("player_id")["team"].transform(lambda team: team != team.shift(1))
    games["team_stint_id"] = team_changed.groupby(games["player_id"]).cumsum()
    games["games_since_trade"] = games.groupby(["player_id", "team_stint_id"]).cumcount()
    return games


def _group_shift(games: pd.DataFrame, column: str, keys: list[str]) -> pd.Series:
    return games.groupby(keys, sort=False)[column].shift(1)


def _group_ewm(
    values: pd.Series, games: pd.DataFrame, keys: list[str], halflife: float
) -> pd.Series:
    """EMA vetorizada por grupo, alinhada pelo índice original das linhas."""
    groupers = [games[key] for key in keys]
    result = values.groupby(groupers, sort=False).ewm(halflife=halflife, min_periods=1).mean()
    return result.reset_index(level=list(range(len(keys))), drop=True).reindex(games.index)


def _group_rolling(
    values: pd.Series, games: pd.DataFrame, keys: list[str], window: int
) -> pd.Series:
    """Média móvel vetorizada por grupo, incluindo apenas valores prévios."""
    groupers = [games[key] for key in keys]
    result = values.groupby(groupers, sort=False).rolling(window=window, min_periods=1).mean()
    return result.reset_index(level=list(range(len(keys))), drop=True).reindex(games.index)

def _prior_date_means(dates: pd.Series, values: pd.Series) -> pd.Series:
    """Média de liga disponível antes de cada data, sem usar a própria data.

    Todos os jogos de uma data usam o mesmo prior construído exclusivamente
    com datas anteriores. Isso evita que o preenchimento de valores ausentes
    incorpore partidas futuras ou partidas do mesmo dia.
    """
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(dates).dt.normalize().to_numpy(),
            "value": pd.to_numeric(values, errors="coerce").to_numpy(dtype=float),
        }
    )
    daily = frame.groupby("date", sort=True)["value"].agg(["sum", "count"])
    prior_sum = daily["sum"].cumsum().shift(1)
    prior_count = daily["count"].cumsum().shift(1)
    return prior_sum.div(prior_count.replace(0, np.nan))


def _past_mean_for_dates(
    source_dates: pd.Series,
    values: pd.Series,
    query_dates: pd.Series,
    default: float,
) -> pd.Series:
    """Média acumulada disponível antes de cada data de consulta.

    Diferentemente de um mapa por data exata, isso também funciona quando a
    partida prevista cai entre duas datas presentes no histórico. O
    ``merge_asof`` usa a última data histórica estritamente anterior, evitando
    vazamento da própria data e de qualquer partida futura.
    """
    source = pd.DataFrame(
        {
            "date": pd.to_datetime(source_dates).dt.normalize().to_numpy(),
            "value": pd.to_numeric(values, errors="coerce").to_numpy(dtype=float),
        }
    ).dropna(subset=["date", "value"])
    daily = source.groupby("date", sort=True)["value"].agg(["sum", "count"]).reset_index()
    daily["mean_to_date"] = daily["sum"].cumsum() / daily["count"].cumsum()

    queries = pd.DataFrame(
        {
            "date": pd.to_datetime(query_dates).dt.normalize().to_numpy(),
            "_row": np.arange(len(query_dates)),
        }
    ).sort_values("date")
    mapped = pd.merge_asof(
        queries,
        daily[["date", "mean_to_date"]].sort_values("date"),
        on="date",
        direction="backward",
        allow_exact_matches=False,
    ).sort_values("_row")
    return pd.Series(mapped["mean_to_date"].fillna(default).to_numpy(), index=query_dates.index)


def _historical_rate(player_games: pd.DataFrame, stat: str) -> pd.Series:
    minutes = pd.to_numeric(player_games["minutes"], errors="coerce")
    values = pd.to_numeric(player_games[stat], errors="coerce")
    return values.div(minutes.where(minutes > 0))


def add_rolling_features(player_games: pd.DataFrame) -> pd.DataFrame:
    """Adiciona variáveis pré-jogo e preenchimentos estritamente temporais.

    Usa operações vetorizadas do pandas para processar a base histórica sem
    executar uma função Python para cada jogador. As características incluem
    janelas dos últimos 3/5/10 jogos e EMAs de carreira/da passagem atual.
    Fallbacks da liga usam somente datas anteriores; no início absoluto da
    série entram os priors fixos documentados em ``INITIAL_PRIORS``.
    """
    if player_games.empty:
        return player_games.copy()

    source = player_games.copy().reset_index(drop=True)
    source["game_date"] = pd.to_datetime(source["game_date"])
    games = assign_team_stints(source).sort_values(["player_id", "game_date"]).copy()
    games["_effective_starter"] = effective_starter_flag(games).astype(float)
    player_keys = ["player_id"]
    stint_keys = ["player_id", "team_stint_id"]

    prior_minutes = _group_shift(games, "minutes", player_keys)
    games["minutes_avg5"] = _group_ewm(prior_minutes, games, player_keys, EMA_HALFLIFE_FAST)
    games["minutes_avg10"] = _group_ewm(prior_minutes, games, player_keys, EMA_HALFLIFE_SLOW)
    prior_dates = _group_shift(games, "game_date", player_keys)
    games["rest_days"] = (games["game_date"] - prior_dates).dt.days

    # EMA e médias curtas das taxas ofensivas/estatísticas.
    for stat in PER_MIN_STATS:
        prior_stat = _group_shift(games, stat, player_keys)
        prior_rate = prior_stat / prior_minutes.replace(0, np.nan)
        games[f"{stat}_per_min_avg10"] = _group_ewm(
            prior_rate, games, player_keys, EMA_HALFLIFE_SLOW
        )
        for window in SHORT_WINDOWS:
            games[f"{stat}_per_min_avg{window}"] = _group_rolling(
                prior_rate, games, player_keys, window
            )

    prior_points = _group_shift(games, "pts", player_keys)
    for window in RECENT_WINDOWS:
        games[f"pts_avg{window}"] = _group_rolling(prior_points, games, player_keys, window)

    prior_ts = _group_shift(games, "true_shooting_pct", player_keys)
    games["ts_pct_avg10"] = _group_ewm(prior_ts, games, player_keys, EMA_HALFLIFE_SLOW)
    for window in SHORT_WINDOWS:
        games[f"ts_pct_avg{window}"] = _group_rolling(prior_ts, games, player_keys, window)

    prior_usage = _group_shift(games, "usage_pct", player_keys)
    games["usg_pct_avg10"] = _group_ewm(prior_usage, games, player_keys, EMA_HALFLIFE_SLOW)
    games["usg_pct_avg5"] = _group_rolling(prior_usage, games, player_keys, 5)
    prior_starter = _group_shift(games, "_effective_starter", player_keys)
    games["starter_rate_avg10"] = _group_ewm(
        prior_starter, games, player_keys, EMA_HALFLIFE_SLOW
    )

    # Repetição para o período de vínculo do jogador ao time atual.
    prior_minutes_stint = _group_shift(games, "minutes", stint_keys)
    games["minutes_avg5_stint"] = _group_ewm(
        prior_minutes_stint, games, stint_keys, EMA_HALFLIFE_FAST
    )
    games["minutes_avg10_stint"] = _group_ewm(
        prior_minutes_stint, games, stint_keys, EMA_HALFLIFE_SLOW
    )
    for stat in PER_MIN_STATS:
        prior_stat = _group_shift(games, stat, stint_keys)
        prior_rate = prior_stat / prior_minutes_stint.replace(0, np.nan)
        games[f"{stat}_per_min_avg10_stint"] = _group_ewm(
            prior_rate, games, stint_keys, EMA_HALFLIFE_SLOW
        )
        for window in SHORT_WINDOWS:
            games[f"{stat}_per_min_avg{window}_stint"] = _group_rolling(
                prior_rate, games, stint_keys, window
            )

    prior_points_stint = _group_shift(games, "pts", stint_keys)
    for window in SHORT_WINDOWS:
        games[f"pts_avg{window}_stint"] = _group_rolling(
            prior_points_stint, games, stint_keys, window
        )
    prior_ts_stint = _group_shift(games, "true_shooting_pct", stint_keys)
    games["ts_pct_avg10_stint"] = _group_ewm(
        prior_ts_stint, games, stint_keys, EMA_HALFLIFE_SLOW
    )
    for window in SHORT_WINDOWS:
        games[f"ts_pct_avg{window}_stint"] = _group_rolling(
            prior_ts_stint, games, stint_keys, window
        )
    prior_usage_stint = _group_shift(games, "usage_pct", stint_keys)
    games["usg_pct_avg10_stint"] = _group_ewm(
        prior_usage_stint, games, stint_keys, EMA_HALFLIFE_SLOW
    )
    games["usg_pct_avg5_stint"] = _group_rolling(prior_usage_stint, games, stint_keys, 5)
    prior_starter_stint = _group_shift(games, "_effective_starter", stint_keys)
    games["starter_rate_avg10_stint"] = _group_ewm(
        prior_starter_stint, games, stint_keys, EMA_HALFLIFE_SLOW
    )

    source_dates = source["game_date"].dt.normalize()
    games_dates = games["game_date"].dt.normalize()
    fallback_specs: dict[str, tuple[pd.Series, float]] = {
        "minutes": (source["minutes"], INITIAL_PRIORS["minutes"]),
        "pts": (source["pts"], INITIAL_PRIORS["pts"]),
        "true_shooting_pct": (
            source["true_shooting_pct"], INITIAL_PRIORS["true_shooting_pct"]
        ),
        "usage_pct": (source["usage_pct"], INITIAL_PRIORS["usage_pct"]),
        "starter_rate": (
            effective_starter_flag(source).astype(float), INITIAL_PRIORS["starter_rate"]
        ),
    }
    for stat in PER_MIN_STATS:
        fallback_specs[f"{stat}_per_min"] = (
            _historical_rate(source, stat), INITIAL_PRIORS[f"{stat}_per_min"]
        )
    fallback_maps = {
        key: _prior_date_means(source_dates, values)
        for key, (values, _) in fallback_specs.items()
    }

    def fallback(key: str) -> pd.Series:
        default = fallback_specs[key][1]
        return games_dates.map(fallback_maps[key]).fillna(default).astype(float)

    for column in ("minutes_avg5", "minutes_avg10"):
        games[column] = games[column].fillna(fallback("minutes"))
    games["rest_days"] = games["rest_days"].fillna(DEFAULT_REST_DAYS).clip(lower=0).astype(int)

    for stat in PER_MIN_STATS:
        for suffix in ("avg10", *[f"avg{window}" for window in SHORT_WINDOWS]):
            column = f"{stat}_per_min_{suffix}"
            games[column] = games[column].fillna(fallback(f"{stat}_per_min"))
    for window in RECENT_WINDOWS:
        games[f"pts_avg{window}"] = games[f"pts_avg{window}"].fillna(fallback("pts"))
    for window in SHORT_WINDOWS:
        games[f"ts_pct_avg{window}"] = games[f"ts_pct_avg{window}"].fillna(
            fallback("true_shooting_pct")
        )
    games["ts_pct_avg10"] = games["ts_pct_avg10"].fillna(fallback("true_shooting_pct"))
    games["usg_pct_avg5"] = games["usg_pct_avg5"].fillna(fallback("usage_pct"))
    games["usg_pct_avg10"] = games["usg_pct_avg10"].fillna(fallback("usage_pct"))
    games["starter_rate_avg10"] = games["starter_rate_avg10"].fillna(fallback("starter_rate"))

    games["minutes_avg5_stint"] = games["minutes_avg5_stint"].fillna(games["minutes_avg5"])
    games["minutes_avg10_stint"] = games["minutes_avg10_stint"].fillna(games["minutes_avg10"])
    for stat in PER_MIN_STATS:
        games[f"{stat}_per_min_avg10_stint"] = games[f"{stat}_per_min_avg10_stint"].fillna(
            games[f"{stat}_per_min_avg10"]
        )
        for window in SHORT_WINDOWS:
            column = f"{stat}_per_min_avg{window}_stint"
            games[column] = games[column].fillna(games[f"{stat}_per_min_avg{window}"])
    for window in SHORT_WINDOWS:
        games[f"pts_avg{window}_stint"] = games[f"pts_avg{window}_stint"].fillna(
            games[f"pts_avg{window}"]
        )
        games[f"ts_pct_avg{window}_stint"] = games[f"ts_pct_avg{window}_stint"].fillna(
            games[f"ts_pct_avg{window}"]
        )
    games["ts_pct_avg10_stint"] = games["ts_pct_avg10_stint"].fillna(games["ts_pct_avg10"])
    games["usg_pct_avg5_stint"] = games["usg_pct_avg5_stint"].fillna(games["usg_pct_avg5"])
    games["usg_pct_avg10_stint"] = games["usg_pct_avg10_stint"].fillna(games["usg_pct_avg10"])
    games["starter_rate_avg10_stint"] = games["starter_rate_avg10_stint"].fillna(
        games["starter_rate_avg10"]
    )

    games = games.drop(columns=["_effective_starter"])
    return games.sort_values(["game_date", "player_id"]).reset_index(drop=True)

def _team_long_defense(team_games: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por time por jogo, com os pontos sofridos naquele jogo."""
    home = team_games[["game_date", "home_team", "away_points"]].rename(
        columns={"home_team": "team", "away_points": "points_allowed"}
    )
    away = team_games[["game_date", "away_team", "home_points"]].rename(
        columns={"away_team": "team", "home_points": "points_allowed"}
    )
    long = pd.concat([home, away], ignore_index=True)
    long["game_date"] = pd.to_datetime(long["game_date"])
    return long.sort_values(["team", "game_date"]).reset_index(drop=True)


def _expanding_defense(group: pd.DataFrame) -> pd.DataFrame:
    """Média expansiva de pontos sofridos, só com jogos anteriores (sem vazamento).

    Expansiva (não janela curta) porque a força defensiva de um time muda
    pouco de uma semana para outra — uma janela de 10 jogos do adversário
    seria mais ruído do que sinal.
    """
    group = group.sort_values("game_date").copy()
    group["opponent_def_rating"] = group["points_allowed"].shift(1).expanding(min_periods=1).mean()
    return group


def add_opponent_context(player_games: pd.DataFrame, team_games: pd.DataFrame) -> pd.DataFrame:
    """Adiciona `opponent_def_rating`: força defensiva do adversário até aquela data.

    Usa o jogo de time mais recente conhecido até a data do jogo do jogador
    (`merge_asof`, não uma correspondência exata de data) — funciona tanto com
    dados reais (mesmo calendário) quanto com a base demonstrativa (calendários
    de time e de jogador gerados de forma independente). Quando não há nenhum
    jogo anterior do adversário, cai na média da liga.

    `player_game_stats.opponent` guarda a sigla do time (ex.: "PHI"), enquanto
    `games.home_team`/`away_team` guarda o nome completo (ex.: "Philadelphia
    76ers") — a coleta de jogadores e a de times vêm de formatos diferentes da
    nba_api. A junção é feita por um nome completo derivado da sigla (ver
    `src/nba_teams.py::TEAM_ABBREVIATION_TO_NAME`); se o valor já for um nome
    completo (caso da base demonstrativa), usa direto.
    """
    games = player_games.copy()
    games["game_date"] = pd.to_datetime(games["game_date"])
    games["_opponent_join_key"] = games["opponent"].map(
        lambda value: TEAM_ABBREVIATION_TO_NAME.get(value, value)
    )

    defense = _team_long_defense(team_games)
    team_column = defense[["team"]]
    defense = defense.groupby("team", group_keys=False).apply(
        _expanding_defense, include_groups=False
    )
    defense = defense.join(team_column)

    # Fallback temporal: média da liga calculada somente com jogos encerrados
    # antes da data prevista. No início absoluto da base, usa-se um prior
    # neutro em vez da média de toda a série (que vazaria dados futuros).

    defense_lookup = (
        defense.rename(columns={"team": "_opponent_join_key"})[
            ["_opponent_join_key", "game_date", "opponent_def_rating"]
        ]
        .dropna(subset=["opponent_def_rating"])
        .sort_values("game_date")
        .reset_index(drop=True)
    )

    merged = pd.merge_asof(
        games.sort_values("game_date").reset_index(drop=True),
        defense_lookup,
        on="game_date",
        by="_opponent_join_key",
        direction="backward",
    )
    temporal_league_fallback = _past_mean_for_dates(
        defense["game_date"],
        defense["points_allowed"],
        merged["game_date"],
        default=110.0,
    )
    merged["opponent_def_rating"] = merged["opponent_def_rating"].fillna(temporal_league_fallback)
    return merged.drop(columns=["_opponent_join_key"]).sort_values("game_date").reset_index(drop=True)
