"""Constantes e estrutura do modelo de zonas de arremesso."""

from __future__ import annotations

from dataclasses import dataclass

from sklearn.pipeline import Pipeline

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


@dataclass
class ZoneModelBundle:
    share_models: dict[str, Pipeline]
    fg_pct_models: dict[str, Pipeline | None]
    metrics: dict[str, float]
    residual_std_share: dict[str, float]
    residual_std_fg_pct: dict[str, float]
    league_avg_share: dict[str, float]
    league_avg_fg_pct: dict[str, float]
