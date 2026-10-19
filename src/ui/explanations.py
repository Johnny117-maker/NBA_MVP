from __future__ import annotations

import pandas as pd

# Diferença mínima para uma mudança de zona virar frase (seção 10 do
# planejamento de UI/UX: "o tamanho da mudança"). Abaixo disso, é ruído mais
# do que sinal — a explicação fica só na frase de destaque, sem inventar uma
# tendência que não existe.
MIN_FREQUENCY_SHIFT = 0.03
MIN_EFFICIENCY_SHIFT = 0.05


def _format_percentage_points(value: float) -> str:
    """Magnitude em pontos percentuais, sem sinal: 0.08 -> "8 p.p.".

    Sem sinal de propósito — sempre usado ao lado de uma palavra de direção
    ("aumentou"/"reduziu", "melhorou"/"piorou"); um "+" na frente contradiria
    "reduziu 10 p.p.", por exemplo.
    """
    return f"{abs(value) * 100:.0f} p.p."


def explain_zone_shift(
    comparison: pd.DataFrame,
    label_a: str = "período anterior",
    label_b: str = "período atual",
    min_sample_attempts: int = 15,
) -> str:
    """Explicação automática em linguagem natural de como a distribuição de
    arremessos por zona mudou entre dois recortes (seção 10 do planejamento
    de UI/UX — mesmo espírito do exemplo: "O jogador concentra 39% das
    tentativas próximas ao aro. Desde a mudança de time, aumentou em 8 pontos
    percentuais a frequência de arremessos de três...").

    `comparison` é o retorno de `src/shot_features.py::compare_periods`.
    Linguagem sempre cautelosa ("os dados indicam", "há sinais de") — nunca
    afirma causa, só descreve o tamanho da mudança; quando a amostra de uma
    zona é pequena demais para falar de eficiência com confiança, diz isso
    explicitamente em vez de generalizar.
    """
    if comparison.empty or comparison["attempts_b"].sum() == 0:
        return "Sem arremessos suficientes para gerar uma explicação."

    # "em {label}" em vez de "no {label}"/"do {label}": os rótulos vêm de quem
    # chama (podem ser "2023-24", "últimos 10 jogos", "casa"...) e um artigo
    # fixo ("o"/"no") erraria gênero ou número dependendo do rótulo — "em"/
    # "comparando ... com ..." não flexiona, então funciona para qualquer um.
    dominant = comparison.sort_values("attempts_b", ascending=False).iloc[0]
    sentences = [
        f"Os dados indicam que, em {label_b}, o jogador concentra "
        f"{dominant['frequency_b']:.0%} das tentativas em {dominant['zone_label'].lower()}."
    ]

    with_shift = comparison.copy()
    with_shift["frequency_shift"] = with_shift["frequency_b"] - with_shift["frequency_a"]
    biggest_shift = with_shift.loc[with_shift["frequency_shift"].abs().idxmax()]
    if abs(biggest_shift["frequency_shift"]) >= MIN_FREQUENCY_SHIFT:
        direction = "aumentou" if biggest_shift["frequency_shift"] > 0 else "reduziu"
        sentences.append(
            f"Comparando {label_a} com {label_b}, {direction} em "
            f"{_format_percentage_points(abs(biggest_shift['frequency_shift']))} a frequência de "
            f"arremessos em {biggest_shift['zone_label'].lower()}."
        )

    qualified = with_shift[
        (with_shift["attempts_a"] >= min_sample_attempts)
        & (with_shift["attempts_b"] >= min_sample_attempts)
    ].copy()
    if qualified.empty:
        sentences.append(
            "A amostra ainda é pequena para comparar aproveitamento por zona com confiança."
        )
    else:
        qualified["fg_pct_shift"] = qualified["fg_pct_b"] - qualified["fg_pct_a"]
        biggest_efficiency_shift = qualified.loc[qualified["fg_pct_shift"].abs().idxmax()]
        if abs(biggest_efficiency_shift["fg_pct_shift"]) >= MIN_EFFICIENCY_SHIFT:
            direction = "melhorou" if biggest_efficiency_shift["fg_pct_shift"] > 0 else "piorou"
            sentences.append(
                f"Há sinais de que o aproveitamento em "
                f"{biggest_efficiency_shift['zone_label'].lower()} {direction} "
                f"({_format_percentage_points(abs(biggest_efficiency_shift['fg_pct_shift']))})."
            )

    return " ".join(sentences)
