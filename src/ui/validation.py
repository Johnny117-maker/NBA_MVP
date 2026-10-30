from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from src.app_paths import RESOURCE_ROOT
from src.prop_training import VERSION


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def validation_report(path: str) -> dict:
    candidates = [RESOURCE_ROOT / "docs/validation/props_validation.json"]
    model_root = Path(path).parent.parent / "models/props"
    if model_root.is_dir():
        candidates = (
            sorted(model_root.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
            + candidates
        )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            body = json.loads(candidate.read_text(encoding="utf-8"))
            report = body.get("validation", body)
            if report.get("policy") == VERSION and report.get("stats"):
                return report
        except (ValueError, OSError):
            continue
    return {}


def validation_panel(path: str | Path) -> None:
    st.subheader("Comprovação em dados separados do treino")
    st.caption(
        "Este é um teste histórico reconstruído. As capturas realmente salvas antes dos jogos "
        "são avaliadas separadamente em Capturas pré-jogo."
    )
    report = validation_report(str(path))
    if not report:
        st.info("Aguardando teste externo para esta versão do modelo. Não há qualidade comprovada ainda.")
        return
    st.write(
        f"Período avaliado: {report['start']} a {report['end']} · {report['player_games']} jogos de atletas."
    )
    rows = []
    labels = {"pts": "Pontos", "reb": "Rebotes", "ast": "Assistências"}
    for stat, evidence in report["stats"].items():
        gain = evidence.get("improvement", {})
        rows.append(
            {
                "Estatística": labels[stat],
                "Evidência": evidence["status"],
                "Observações": evidence["n"],
                "Erro do modelo": evidence.get("mae"),
                "Erro da média recente": evidence.get("reference_mae"),
                "Ganho mínimo IC95%": gain.get("low"),
                "Ganho máximo IC95%": gain.get("high"),
                "Cobertura da faixa": evidence.get("coverage"),
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        alt="Modelo comparado à média das últimas dez partidas em janelas externas",
    )
    st.caption(
        "Menor erro é melhor. Um ganho positivo favorece o modelo. Se o intervalo de 95% inclui zero, "
        "o teste não demonstra vantagem. A faixa P10–P90 tem referência nominal de 80%; "
        "contagens inteiras podem aumentar a cobertura."
    )
    st.info(
        "Resultados históricos não comprovam acerto futuro, lucro "
        "ou qualidade para cada jogador individualmente."
    )
    with st.expander("Datas, cobertura e reprodução do teste"):
        st.write(report["protocol"])
        st.write(report["uncertainty"])
        st.write(report["limits"])
        st.dataframe(
            pd.DataFrame(report["windows"]),
            hide_index=True,
            alt="Corte de treino anterior a cada janela de teste externo",
        )
        st.caption("Identificação: " + report["id"])
        st.download_button(
            "Baixar relatório de validação",
            json.dumps(report, ensure_ascii=False, indent=2),
            file_name="validacao_player_props.json",
            mime="application/json",
        )
