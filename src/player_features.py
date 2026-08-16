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

STINT_COLUMNS = [
    "minutes_avg5_stint",
    "minutes_avg10_stint",
    *(f"{stat}_per_min_avg10_stint" for stat in PER_MIN_STATS),
    "ts_pct_avg10_stint",
    "usg_pct_avg10_stint",
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


def _per_player_rolling(group: pd.DataFrame) -> pd.DataFrame:
    """Médias exponenciais (carreira inteira) usando apenas jogos anteriores (sem vazamento).

    Os nomes das colunas (`_avg5`/`_avg10`) são os mesmos de antes — só a
    fórmula por trás mudou de janela flat para média móvel exponencial.
    """
    group = group.sort_values("game_date").copy()
    group["minutes_avg5"] = (
        group["minutes"].shift(1).ewm(halflife=EMA_HALFLIFE_FAST, min_periods=1).mean()
    )
    group["minutes_avg10"] = (
        group["minutes"].shift(1).ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
    )
    group["rest_days"] = (group["game_date"] - group["game_date"].shift(1)).dt.days

    prior_minutes = group["minutes"].shift(1)
    for stat in PER_MIN_STATS:
        prior_rate = group[stat].shift(1) / prior_minutes.replace(0, np.nan)
        group[f"{stat}_per_min_avg10"] = (
            prior_rate.ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
        )

    group["ts_pct_avg10"] = (
        group["true_shooting_pct"].shift(1).ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
    )
    group["usg_pct_avg10"] = (
        group["usage_pct"].shift(1).ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
    )
    group["starter_rate_avg10"] = (
        group["_effective_starter"].shift(1).ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
    )
    return group


def _per_stint_rolling(group: pd.DataFrame) -> pd.DataFrame:
    """Iguais às médias de carreira, mas só com jogos da passagem (time) atual."""
    group = group.sort_values("game_date").copy()
    group["minutes_avg5_stint"] = (
        group["minutes"].shift(1).ewm(halflife=EMA_HALFLIFE_FAST, min_periods=1).mean()
    )
    group["minutes_avg10_stint"] = (
        group["minutes"].shift(1).ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
    )

    prior_minutes = group["minutes"].shift(1)
    for stat in PER_MIN_STATS:
        prior_rate = group[stat].shift(1) / prior_minutes.replace(0, np.nan)
        group[f"{stat}_per_min_avg10_stint"] = (
            prior_rate.ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
        )

    group["ts_pct_avg10_stint"] = (
        group["true_shooting_pct"].shift(1).ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
    )
    group["usg_pct_avg10_stint"] = (
        group["usage_pct"].shift(1).ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
    )
    group["starter_rate_avg10_stint"] = (
        group["_effective_starter"].shift(1).ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
    )
    return group


def add_rolling_features(player_games: pd.DataFrame) -> pd.DataFrame:
    """Adiciona médias móveis (sem vazamento) usadas para treinar o modelo de projeção.

    Duas versões de cada média: `_avg10` (carreira inteira) e `_avg10_stint`
    (só a passagem atual pelo time, reiniciada a cada troca — ver
    `assign_team_stints`). Nos primeiros jogos de uma passagem nova, a versão
    "_stint" ainda não tem histórico suficiente e cai na versão de carreira
    (o passado continua influenciando, só que com o modelo aprendendo a dar
    menos peso a ele à medida que `games_since_trade` cresce).
    """
    games = assign_team_stints(player_games)
    games["_effective_starter"] = effective_starter_flag(games).astype(float)
    player_ids = games[["player_id"]]

    games = games.groupby("player_id", group_keys=False).apply(
        _per_player_rolling, include_groups=False
    )
    games = games.join(player_ids)

    league_avg_minutes = float(player_games["minutes"].mean())
    games["minutes_avg5"] = games["minutes_avg5"].fillna(league_avg_minutes)
    games["minutes_avg10"] = games["minutes_avg10"].fillna(league_avg_minutes)
    games["rest_days"] = games["rest_days"].fillna(DEFAULT_REST_DAYS).astype(int)

    for stat in PER_MIN_STATS:
        valid_minutes = player_games["minutes"] > 0
        league_avg_rate = float(
            (player_games.loc[valid_minutes, stat] / player_games.loc[valid_minutes, "minutes"]).mean()
        )
        games[f"{stat}_per_min_avg10"] = games[f"{stat}_per_min_avg10"].fillna(league_avg_rate)

    league_avg_ts_pct = float(player_games["true_shooting_pct"].mean())
    games["ts_pct_avg10"] = games["ts_pct_avg10"].fillna(league_avg_ts_pct)

    league_avg_usg_pct = float(player_games["usage_pct"].mean())
    games["usg_pct_avg10"] = games["usg_pct_avg10"].fillna(league_avg_usg_pct)

    league_avg_starter_rate = float(games["_effective_starter"].mean())
    games["starter_rate_avg10"] = games["starter_rate_avg10"].fillna(league_avg_starter_rate)

    stint_result = games.groupby(["player_id", "team_stint_id"], group_keys=False).apply(
        _per_stint_rolling, include_groups=False
    )
    games = games.join(stint_result[STINT_COLUMNS])

    games["minutes_avg5_stint"] = games["minutes_avg5_stint"].fillna(games["minutes_avg5"])
    games["minutes_avg10_stint"] = games["minutes_avg10_stint"].fillna(games["minutes_avg10"])
    for stat in PER_MIN_STATS:
        games[f"{stat}_per_min_avg10_stint"] = games[f"{stat}_per_min_avg10_stint"].fillna(
            games[f"{stat}_per_min_avg10"]
        )
    games["ts_pct_avg10_stint"] = games["ts_pct_avg10_stint"].fillna(games["ts_pct_avg10"])
    games["usg_pct_avg10_stint"] = games["usg_pct_avg10_stint"].fillna(games["usg_pct_avg10"])
    games["starter_rate_avg10_stint"] = games["starter_rate_avg10_stint"].fillna(
        games["starter_rate_avg10"]
    )

    games = games.drop(columns=["_effective_starter"])
    return games.sort_values("game_date").reset_index(drop=True)


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

    league_avg = float(defense["points_allowed"].mean())

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
    merged["opponent_def_rating"] = merged["opponent_def_rating"].fillna(league_avg)
    return merged.drop(columns=["_opponent_join_key"]).sort_values("game_date").reset_index(drop=True)
