import json
from datetime import timedelta

import pandas as pd
import streamlit as st

from src.analysis_archive import archive_path, read_snapshots
from src.live_types import EASTERN, current_season, utc_now
from src.research_feeds import collect_rim_defense, import_metrics, read_metrics
from src.research_metrics import fit_rapm, off_ball_gravity
from src.shot_quality import expected_points, train_location_quality
from src.store import DEFAULT_DB_PATH
from src.ui import components, theme
from src.ui.learning import learning_status

st.set_page_config(
    page_title="Laboratório — NBA Analytics Lab", page_icon=":material/science:", layout="wide"
)
theme.inject_base_style("research")
components.page_header(
    "Modelos que podemos medir.",
    "Explore o treino temporal, as métricas calculadas e a disponibilidade dos dados de impacto e tracking.",
    category="LABORATÓRIO DE MODELOS",
)
mode = st.segmented_control(
    "Explorar modelos",
    [
        "Player props",
        "Aprendizado automático",
        "Métricas e fontes",
        "RAPM",
        "Qualidade do arremesso",
        "Gravity",
    ],
    default="Player props",
    required=True,
)
today = utc_now().astimezone(EASTERN).date()
model_dir = DEFAULT_DB_PATH.parent.parent / "models" / "research"
if mode == "Aprendizado automático":
    learning_status(DEFAULT_DB_PATH, detailed=True)
elif mode == "Player props":
    st.subheader("Bayes + XGBoost")
    st.caption(
        "Gamma-Poisson estima PTS, REB e AST; Beta-Binomial estabiliza conversões de arremesso. "
        "Um filtro dinâmico local acompanha a taxa de produção. XGBoost aprende relações com minutos "
        "recentes, descanso, casa/fora, adversário, eficiência e volume."
    )
    records = read_snapshots(DEFAULT_DB_PATH, limit=10)
    trained = next((s["model"] for s in records if s["model"].get("metrics")), None)
    if trained:
        st.caption(
            f"Treino inicial até {trained['fit_end']} · calibração desde {trained['calibration_start']} · "
            f"teste de {trained['test_start']} a {trained['test_end']} · "
            f"{trained['test_rows']} observações no teste"
        )
        st.dataframe(
            pd.DataFrame(trained["metrics"]).T.rename_axis("Estatística").reset_index(),
            hide_index=True,
            alt="Erros no teste temporal separado: Bayes, XGBoost e combinação selecionada na calibração",
        )
        st.caption(f"Peso de XGBoost escolhido na calibração: {trained['weights']}")
        st.caption(
            "Peso zero preserva o modelo bayesiano quando o ML não melhora a calibração em pelo menos 1%. "
            "MAE mede a média prevista; não comprova calibração de probabilidades Over/Under."
        )
        st.json(trained, expanded=False)
    else:
        st.info(
            "O monitor treina e arquiva o primeiro modelo quando encontra jogos futuros "
            "e histórico suficiente."
        )
    st.caption("Os modelos antigos das demais análises continuam identificados nas suas telas.")
elif mode == "Métricas e fontes":
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Métrica": "TS%, USG%, AST Ratio / TOV Ratio",
                    "Estado": "Calculadas com boxscores",
                    "Requisito": "USG estimado por totais de jogadores; pode omitir eventos só de equipe",
                },
                {
                    "Métrica": "LEBRON / O-LEBRON / D-LEBRON",
                    "Estado": "Importação de publicação externa",
                    "Requisito": "Valores Basketball Index com ID NBA, data de referência e fonte",
                },
                {
                    "Métrica": "DARKO DPM",
                    "Estado": "Importação de publicação externa",
                    "Requisito": "Valores DARKO com ID NBA, data de referência e fonte",
                },
                {
                    "Métrica": "DFG% a menos de 6 pés",
                    "Estado": "Coletor nba_api disponível",
                    "Requisito": "Resposta do endpoint de tracking NBA; alcance de rede necessário",
                },
                {
                    "Métrica": "RAPM",
                    "Estado": "Ridge ponderado por posses",
                    "Requisito": "Escalações completas e posses medidas em cada stint",
                },
                {
                    "Métrica": "xP por localização",
                    "Estado": "Classificador XGBoost",
                    "Requisito": "ShotChartDetail; sem distância do defensor ou relógio de posse",
                },
                {
                    "Métrica": "Gravity local",
                    "Estado": "Cálculo sobre tracking externo",
                    "Requisito": "Frames, defensor atribuído e referência; indisponível no boxscore",
                },
            ]
        ),
        hide_index=True,
        alt="Disponibilidade e requisitos dos indicadores de análise",
    )
    st.caption(
        "LEBRON e DARKO são indicadores de impacto, não linhas de pontos. Os valores importados ficam como "
        "contexto, sem entrar retroativamente no treino. A disponibilidade só começa na data da importação."
    )
    if st.button("Consultar proteção de aro na NBA", icon=":material/cloud_download:"):
        try:
            with st.spinner("Consultando nba_api..."):
                count = collect_rim_defense(DEFAULT_DB_PATH, current_season(today), today - timedelta(days=1))
            st.success(f"{count} indicadores de defesa importados.")
        except Exception as error:
            st.warning(f"A NBA não forneceu os dados nesta consulta ({type(error).__name__}).")
    upload = st.file_uploader("Importar métricas publicadas (CSV)", type=["csv"])
    st.caption("Colunas: metric, player_id, as_of, value, source. LEBRON e DARKO exigem a fonte do produtor.")
    if upload is not None and st.button("Importar arquivo de métricas"):
        try:
            st.success(f"{import_metrics(DEFAULT_DB_PATH, pd.read_csv(upload))} indicadores importados.")
        except (ValueError, TypeError, KeyError) as error:
            st.error(str(error))
    if archive_path(DEFAULT_DB_PATH).exists():
        metrics = read_metrics(DEFAULT_DB_PATH)
        if not metrics.empty:
            st.dataframe(
                metrics, hide_index=True, alt="Indicadores importados com fonte e data de disponibilidade"
            )
elif mode == "RAPM":
    st.caption(
        "Saldo por 100 posses = escalação da casa (+1) e visitante (−1), com regularização Ridge. "
        "Amostras pequenas e escalações repetidas geram muita incerteza. Alpha é uma escolha explícita."
    )
    upload = st.file_uploader("Stints validados (CSV)", type=["csv"])
    st.caption("Colunas: home_players, away_players (listas JSON de cinco IDs), points_diff, possessions.")
    alpha = st.number_input("Regularização Ridge (alpha)", min_value=1.0, value=2000.0)
    if upload is not None and st.button("Calcular RAPM dos stints"):
        try:
            result = fit_rapm(pd.read_csv(upload), alpha)
            st.caption(f"{result.stints} stints · {result.possessions:.0f} posses · alpha {result.alpha:g}")
            st.dataframe(result.ratings, hide_index=True, alt="RAPM local por jogador e exposição em posses")
            st.download_button("Baixar RAPM calculado", result.ratings.to_csv(index=False), "rapm_local.csv")
        except (ValueError, TypeError, KeyError) as error:
            st.error(str(error))
elif mode == "Qualidade do arremesso":
    st.caption(
        "xP de localização = valor do arremesso × probabilidade de acerto. Usa distância, ângulo, "
        "tipo e período. ShotChartDetail não traz tracking do defensor. Este modelo não mede esse componente."
    )
    if st.button("Treinar xP com os arremessos coletados"):
        try:
            with st.spinner("Treinando em até 60 mil tentativas, com teste temporal..."):
                report = train_location_quality(DEFAULT_DB_PATH, model_dir, today.isoformat())
            st.success(f"Treino concluído com {report['rows']} tentativas.")
        except (ValueError, KeyError, ImportError) as error:
            st.error(str(error))
    if (model_dir / "shot_location_manifest.json").exists():
        report = json.loads((model_dir / "shot_location_manifest.json").read_text(encoding="utf-8"))
        st.json(report, expanded=False)
        distance = st.slider("Distância (pés)", 1.0, 40.0, 24.0)
        angle = st.slider("Ângulo absoluto em relação ao aro (graus)", 0.0, 180.0, 30.0)
        value = st.segmented_control("Valor da tentativa", [2, 3], default=3, required=True)
        estimate = expected_points(model_dir, distance=distance, angle=angle, value=int(value))
        st.metric("Pontos esperados por tentativa", f"{estimate['expected_points']:.2f}")
        st.caption(
            f"Probabilidade de acerto: {estimate['make_probability']:.1%} · cenário fixo: Q2, 6 minutos"
        )
elif mode == "Gravity":
    st.caption(
        "Indicador local em pés: distância de referência menos a distância real do defensor atribuído, "
        "ponderada pela duração. Mede aproximação defensiva fora da bola. Exige tracking externo em pés."
    )
    upload = st.file_uploader("Frames de tracking (CSV)", type=["csv"])
    st.caption(
        "Colunas: frame_id, player_id, ball_handler_id, x, y, defender_x, defender_y, "
        "baseline_distance, duration (segundos). Não há tracking óptico na base atual."
    )
    if upload is not None and st.button("Calcular Gravity local"):
        try:
            result = off_ball_gravity(pd.read_csv(upload))
            st.dataframe(result, hide_index=True, alt="Aproximação defensiva local por jogador fora da bola")
            st.download_button("Baixar Gravity local", result.to_csv(index=False), "gravity_local.csv")
        except (ValueError, TypeError, KeyError) as error:
            st.error(str(error))
