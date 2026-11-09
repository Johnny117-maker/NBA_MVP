# Pendências que exigem a base real (bloco D do plano de melhorias)

Em 08/11/2026 não havia `data/nba.db` real onde o plano foi executado (só bancos temporários de
teste), e o ambiente não tem acesso à rede da NBA. Por isso os itens D1 a D5 **não foram executados**
e nenhum número novo foi escrito na documentação. Rode os passos abaixo onde a base existir
(use `make` ou os `.bat` equivalentes na pasta `windows/`).

## Preparação (uma vez)

```bash
python scripts/sync_current_season.py --once                 # temporada atual
python scripts/collect_history.py --start-year 2022          # acervo público desde 2022 (retomável)
python scripts/update_advanced_stats.py --limit 200 --delay 1   # repita até zerar os jogos pendentes (D3)
python scripts/update_starter_status.py --limit 200 --delay 1   # idem, titularidade (D3)
```

Os dois últimos fazem uma chamada por jogo e continuam de onde pararam: repita até a cobertura
de ratings oficiais e de titularidade parar de crescer.

## D1. Recalcular as métricas dos modelos de zonas

```bash
python scripts/retrain_models.py
python scripts/audit_models.py --db data/nba.db --players --output reports/model_audit_<AAAA-MM-DD>.json
```

Depois: atualizar `docs/AUDITORIA_MODELOS_2026-10-27.md` com os números do arquivo gerado, registrando
data e versão do modelo (`SCORE_MODEL_VERSION`, versão dos modelos de jogadores). Só use valores que
vieram dessa execução.

## D2. Peso do XGBoost igual a zero

Rode `python scripts/validate_player_props.py --db data/nba.db --before-day <AAAA-MM-DD> --output docs/validation/props_validation.json`
e compare janelas maiores, mais features (D3) e busca de hiperparâmetros com validação temporal
(`walk_forward_evaluate`). Se continuar sem ganho, documente e avalie simplificar o pipeline.

## D3. Cobertura de entrada

Meça, antes e depois das coletas acima, a cobertura de ratings oficiais, de titularidade e de lesões
(painel de qualidade dos dados da página **Dados e atualizações** e `scripts/audit_models.py`), e o ganho do modelo de minutos sobre a
referência (hoje 0,33% segundo a auditoria). A avaliação de uma fonte de lesões históricas é um estudo
à parte: documente prós, contras e limites de cada fonte.

## D4. Placar de times: promover o candidato corrigido

Repita a avaliação nas três últimas temporadas com a versão corrigida
(`python scripts/retrain_models.py --team-only` e `scripts/audit_models.py`). Se o ganho se mantiver,
registre em `reports/model_promotion_*.json` e só altere `SCORE_MODEL_VERSION` se necessário.
Os resultados do modelo Elo de 08/11/2026 estão em `docs/MODELO_TIMES_ELO.md`.

## D5. Calibração do classificador de times

Gere a curva de confiabilidade por faixas de probabilidade e compare calibração isotônica e Platt em
dados fora da amostra, mantendo a que melhorar log loss e Brier. Documente os números da execução.
