from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import generate_demo_games, load_real_games  # noqa: E402
from src.logging_setup import configure_logging  # noqa: E402
from src.model import train_models  # noqa: E402
from src.player_data import load_player_games  # noqa: E402
from src.player_features import add_opponent_context, add_rolling_features  # noqa: E402
from src.player_model import walk_forward_evaluate  # noqa: E402
from src.shot_model import add_zone_model_features, walk_forward_evaluate_zone_models  # noqa: E402
from src.shot_storage import count_player_shots, read_shots_for_zone_reference  # noqa: E402
from src.store import DEFAULT_DB_PATH, count_games, count_player_games, log_model_training  # noqa: E402

MIN_GAMES_FOR_ZONE_WALK_FORWARD = 60


def _load_team_games():
    if count_games(DEFAULT_DB_PATH) > 0:
        return load_real_games(DEFAULT_DB_PATH), "real"
    print("  Nenhum jogo real coletado ainda — usando a base demonstrativa.")
    return generate_demo_games(), "demo"


def _load_player_games():
    if count_player_games(DEFAULT_DB_PATH) > 0:
        return load_player_games(source="real", db_path=DEFAULT_DB_PATH), "real"
    print("  Nenhum jogador real coletado ainda — usando a base demonstrativa.")
    return load_player_games(source="demo"), "demo"


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Retreina e registra as métricas dos modelos locais.")
    parser.add_argument("--team-only", action="store_true", help="Treina somente os modelos de times.")
    args = parser.parse_args(argv)
    print("Retreinando modelo de times...")
    team_games, team_source = _load_team_games()
    team_bundle = train_models(team_games)
    log_model_training("team", len(team_games), team_bundle.metrics, DEFAULT_DB_PATH)
    print(f"  Fonte: {team_source} | {len(team_games)} jogos | métricas: {team_bundle.metrics}")
    if args.team_only:
        return

    print("Avaliando modelo de jogadores (validação walk-forward)...")
    player_games, player_source = _load_player_games()
    features = add_opponent_context(add_rolling_features(player_games), team_games)
    # Walk-forward é mais caro que um split único (retreina várias vezes),
    # mas dá uma métrica mais confiável para o histórico — por isso só roda
    # aqui, não a cada carregamento da página (ver src/player_model.py).
    evaluation = walk_forward_evaluate(features)
    log_model_training("player", len(player_games), evaluation["aggregate"], DEFAULT_DB_PATH)

    # Grava também a previsão de cada jogador-partida no teste temporal, não
    # apenas métricas agregadas. A tela de qualidade usa esse arquivo para a
    # auditoria por rodada e para baixar erros individuais.
    report_dir = Path(__file__).resolve().parent.parent / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "player_backtest_predictions.csv"
    evaluation["predictions"].to_csv(report_path, index=False, encoding="utf-8-sig")

    print(
        f"  Fonte: {player_source} | {len(player_games)} linhas | "
        f"{evaluation['aggregate']['n_folds']} folds | "
        f"previsões auditadas: {len(evaluation['predictions'])} | "
        f"arquivo: {report_path} | "
        f"métricas agregadas: {evaluation['aggregate']}"
    )

    print("Avaliando modelo de zonas de arremesso (validação walk-forward)...")
    if count_player_shots(DEFAULT_DB_PATH) == 0:
        print("  Nenhum arremesso coletado ainda — pulando (não há base demonstrativa para zonas).")
    else:
        zone_reference = read_shots_for_zone_reference(DEFAULT_DB_PATH)
        zone_games = add_zone_model_features(zone_reference)
        if len(zone_games) < MIN_GAMES_FOR_ZONE_WALK_FORWARD * 2:
            print(
                f"  Só {len(zone_games)} jogos com arremessos coletados — poucos para "
                "validação walk-forward dos modelos de zona, pulando."
            )
        else:
            zone_evaluation = walk_forward_evaluate_zone_models(
                zone_games, min_train_games=MIN_GAMES_FOR_ZONE_WALK_FORWARD
            )
            log_model_training("zone", len(zone_games), zone_evaluation["aggregate"], DEFAULT_DB_PATH)
            print(
                f"  {len(zone_games)} jogos | {zone_evaluation['aggregate']['n_folds']} folds | "
                f"MAE de pontos de bola-de-quadra: {zone_evaluation['aggregate']['fg_points_mae']:.2f}"
            )

    print("Retreinamento concluído. Veja o histórico na página 'Qualidade do Modelo' do app.")


if __name__ == "__main__":
    main()
