# Plano de melhorias — NBA Analytics Lab (repo `NBA_MVP`)

Resultado da análise do projeto. Cada item tem prioridade, arquivos envolvidos, o que fazer e o critério de aceite.

**Estado de partida (verificado):** `pytest` com 457 testes passando e 3 ignorados, `ruff` sem erros e `mypy` sem erros em 120 arquivos.
**Regra geral:** nenhuma tarefa pode piorar esse estado. Ao final de cada bloco, rodar:

```bash
python -m ruff check .
python -m mypy src pages app.py desktop_launcher.py scripts
python -m pytest -q
```

**Restrições que valem para tudo:**
- Não alterar nem reescrever previsões pré-jogo já preservadas (histórico com SHA-256).
- Não mudar o comportamento dos modelos em produção sem teste que comprove o resultado.
- Não commitar bancos de dados, modelos treinados nem segredos.

---

## Legenda de prioridade

- **P0**: rápido e de alto impacto (higiene do repositório)
- **P1**: importante para qualidade e manutenção
- **P2**: melhoria de modelo e dados, exige a base real (`data/nba.db`)
- **P3**: desejável, pode ficar para depois

---

## Bloco A — Higiene do repositório (P0)

### A1. Reescrever o `README.md`
**Problema:** o README tem cerca de 53 KB e é um changelog empilhado (1.6.1, 1.6.0, 1.5.0, ...). Quem chega não descobre rapidamente o que o app faz nem como rodar.

**Fazer:**
- [x] Mover todo o histórico de versões para um novo `CHANGELOG.md`, preservando o texto original.
- [x] Novo `README.md` curto (menos de 150 linhas) com: o que é o projeto (uma frase), principais funcionalidades, captura de tela ou diagrama (reaproveitar `docs/material/*.png` se fizer sentido), requisitos, instalação, como rodar (`streamlit run app.py`), como rodar os testes, estrutura de pastas, links para `docs/` e aviso de que as probabilidades são experimentais.
- [x] Deixar explícito logo no início que o projeto **não** prevê o prêmio de MVP da NBA (o nome do repositório é enganoso).

**Aceite:** o README cabe em uma leitura rápida e todos os links internos funcionam.

### A2. Remover `diagnostico_ui_nba.txt`
**Problema:** arquivo de 104 KB que é só uma cópia do código-fonte em texto.

**Fazer:**
- [x] Remover `diagnostico_ui_nba.txt` do repositório.
- [x] Adicionar `diagnostico_*.txt` ao `.gitignore`.

### A3. Organizar os documentos soltos na raiz
**Problema:** a raiz mistura código, scripts `.bat` e vários documentos de planejamento.

**Arquivos a mover para `docs/planning/`:**
- [x] `planejamento_analise_jogadores_nba.md` — movido para `docs/planning/`
- [x] `planejamento_mapa_arremessos_jogadores_nba.md` — movido para `docs/planning/`
- [x] `planejamento_programa_analise_nba.md` — movido para `docs/planning/`
- [x] `planejamento_ui_ux_nba_analytics.md` — movido para `docs/planning/`
- [x] `modulo_sabermetria_jogadores_nba.md` — movido para `docs/planning/`
- [x] `analise_estatistica_faixas_desempenho_jogadores_nba.md` — movido para `docs/planning/`
- [x] `alteracoes_benchmark_mercado.md` — movido para `docs/planning/`
- [x] `MELHORIAS_PREVISAO_PONTOS.md` — movido para `docs/planning/`

**Fazer também:**
- [x] Atualizar qualquer link que aponte para o local antigo (buscar com `grep -rn` pelos nomes de arquivo).
- [x] Criar `docs/README.md` com um índice curto de todos os documentos, agrupados por tema (modelos e qualidade, dados, interface, executável, planejamento).

### A4. Mover os scripts de Windows
**Problema:** 8 arquivos `.bat` e um `.ps1` ocupam a raiz.

**Fazer:**
- [~] Mover os `.bat` para `windows/` (ou `scripts/windows/`), ajustando caminhos relativos dentro deles. — 8 dos 10 `.bat` movidos; `CRIAR_ATALHO.bat` e `PUBLICAR_GITHUB.bat` ficam na raiz porque o pacote do executável e testes (`test_desktop*.py`, `test_publish_github.py`) dependem do local
- [x] Atualizar README e `docs/EXECUTAVEL_WINDOWS.md` com os novos caminhos.
- [x] Verificar `scripts/prepare_start.ps1` e `scripts/validate_desktop.py` para garantir que não dependem do local antigo. — `schedule_daily_update.ps1` ajustado; `prepare_start.ps1` recebe a raiz por parâmetro e `validate_desktop.py` não referencia `.bat`

**Aceite:** a raiz fica só com `app.py`, `desktop_launcher.py`, configs, `README.md`, `CHANGELOG.md` e pastas.

---

## Bloco B — Dar suporte a Linux/macOS (P1)

**Problema:** o fluxo para o usuário final é só Windows (`.bat`), embora o CI rode em Linux.

**Fazer:**
- [x] Criar `Makefile` (ou `justfile`) com alvos: `install`, `run`, `test`, `lint`, `typecheck`, `update-data`, `retrain`.
- [x] Documentar no README a instalação em Linux/macOS (venv, `pip install -r requirements.txt`, `streamlit run app.py`).
- [x] Garantir que os scripts em `scripts/*.py` rodam sem depender de caminhos ou convenções do Windows (usar `pathlib`). — sem caminhos do Windows nos scripts de dados

**Aceite:** seguindo só o README, alguém em Linux consegue abrir o app e rodar os testes.

---

## Bloco C — Qualidade de código (P1)

### C1. Tratar `except Exception` amplos
**Problema:** há 23 ocorrências em `src/`, `pages/` e `scripts/`. Algumas engolem o erro sem registrar nada.

**Locais para revisar primeiro:**
- [x] `src/season_sync.py` (linhas ~190 e ~325) — revisado: já registrava em log, mantido
- [x] `src/injuries.py` (~296) — revisado e registrado em log
- [x] `src/desktop_runtime.py` (~322) — revisado e registrado em log
- [x] `src/research_feeds.py` (~124) — revisado e registrado em log
- [x] `src/history_sources.py` (~206 e ~247) — revisado e registrado em log
- [x] `src/remote_archive.py` (~284) — revisado e registrado em log

**Fazer:**
- [x] Para cada caso, trocar por exceções específicas (por exemplo `requests.RequestException`, `OSError`, `ValueError`, `sqlite3.Error`) quando for possível identificar quais ocorrem. — todos são limites de fonte externa/thread; mantidos
- [x] Quando o `except` amplo for intencional (falha de fonte externa não pode derrubar o app), manter, mas **registrar** com `logging.getLogger(__name__).warning(..., exc_info=True)` e incluir um comentário curto explicando o motivo.
- [x] Configurar `logging` de forma central (um módulo pequeno, por exemplo `src/logging_setup.py`) e usá-lo em `app.py` e nos scripts.
- [x] Acrescentar testes para pelo menos três desses caminhos de falha, confirmando que o erro é registrado e o fluxo continua.

**Aceite:** nenhum `except Exception: pass` silencioso restante. Ruff com regra `BLE001` ou `S110` pode ser considerada para impedir regressão.

### C2. Quebrar funções muito longas
**Funções-alvo (linhas aproximadas):**
- [x] `pages/0_Times.py::main` (253)
- [x] `src/player_model.py::train_player_models` (187)
- [x] `src/ui/forecast_performance.py::performance_panel` (172)
- [x] `src/player_features.py::add_rolling_features` (170)
- [x] `src/player_model.py::walk_forward_evaluate` (165)
- [x] `src/ui/pick_detail.py::pick_detail` (161)
- [~] `src/desktop_runtime.py::_run_window` (157) — não refatorada: código Qt aninhado sem PySide6 nem testes para provar equivalência (justificado em comentário)
- [x] `src/live_store.py::persist_final` (140)

**Fazer:**
- [x] Extrair funções auxiliares com nomes que descrevam uma etapa (carregar dados, montar features, treinar, avaliar, renderizar seção).
- [x] Refatoração **sem mudar comportamento**: os testes existentes devem continuar passando sem alterações de asserções. — equivalência exata conferida em features, treino e walk-forward
- [x] Nas páginas Streamlit, extrair seções para funções em `src/ui/`.

**Aceite:** nenhuma função com mais de ~80 linhas nos arquivos listados, ou justificativa em comentário.

### C3. Dividir módulos grandes
**Arquivos-alvo:** `src/player_model.py` (1.038 linhas), `src/store.py` (866), `pages/1_Jogadores.py` (852), `src/shot_model.py` (643), `src/player_features.py` (623), `src/analysis_archive.py` (591).

**Fazer:**
- [x] Propor a divisão por responsabilidade antes de mover código. Exemplo para `player_model.py`: `player_model/features.py`, `player_model/training.py`, `player_model/evaluation.py`, `player_model/prediction.py`.
- [x] Manter os imports públicos antigos funcionando (reexportar em `__init__.py`) para não quebrar páginas, scripts e testes.
- [x] Fazer um módulo por vez, com testes verdes entre cada passo.

**Aceite:** nenhum módulo acima de ~600 linhas, sem quebra de imports existentes.

### C4. Corrigir avisos de depreciação
**Fazer:**
- [x] `tests/test_picks_page.py:242`: `pd.Timedelta(hours=2)` com unidade genérica do NumPy. Usar uma forma explícita (`pd.Timedelta(hours=2)` com datetime tz-aware já tipado, ou `np.timedelta64(2, "h")`).
- [x] `tests/test_prop_probability.py:28`: `rows.loc[1, "actual"] = 20.5` em coluna `int64`. Converter a coluna para `float` antes.
- [x] `tests/test_shot_model.py:211`: `pd.Timedelta(days=1000)` com unidade genérica. Tornar explícito.
- [x] Rodar `python -m pytest -q -W error::DeprecationWarning -W error::FutureWarning` para achar outros e, se viável, transformar esses avisos em erro no `pyproject.toml` (`filterwarnings`). — um aviso interno do pandas 2.3 com NumPy 2.5 é ignorado de forma explícita no `pyproject.toml`

**Aceite:** suíte sem `DeprecationWarning`/`FutureWarning` do próprio projeto.

### C5. Remover string fixa do repositório
**Problema:** `Johnny117-maker/NBA_MVP` está escrito direto em `src/remote_archive.py` (linha ~24, `REPOSITORY`) e em `src/ui/remote_archive.py` (linhas ~39 e ~43). Isso quebra se o repo for renomeado ou virar fork.

**Fazer:**
- [x] Ler o repositório de uma variável de ambiente (`NBA_ARCHIVE_REPOSITORY`) ou de `.streamlit/secrets.toml`, mantendo o valor atual como padrão.
- [x] Montar as URLs da UI a partir dessa configuração.
- [x] Atualizar `secrets.example.toml` e a documentação.
- [x] Ajustar/estender os testes de `tests/test_remote_archive.py`.

---

## Bloco D — Modelos e dados (P2)

> Exige a base real. O `data/nba.db` não vai no repositório, então estes itens precisam ser executados onde a base existe (`scripts/collect_history.py`, `scripts/sync_current_season.py`).

### D1. Recalcular as métricas dos modelos de zonas
**Problema:** `docs/AUDITORIA_MODELOS_2026-10-27.md` diz que as métricas de zonas foram calculadas **antes** da correção do vazamento (priors fixos por zona e corte por data inteira) e precisam ser refeitas.

**Fazer:**
- [ ] Rodar `scripts/retrain_models.py` e `scripts/audit_models.py` com a base real.
- [ ] Atualizar `reports/model_audit_*.json` e o texto do documento de auditoria com os números novos.
- [ ] Registrar a data e a versão do modelo.

### D2. Investigar por que o peso do XGBoost é 0
**Problema:** em `docs/validation/props_validation.json`, os pesos `pts`, `reb` e `ast` ficaram em `0.0` nas duas janelas externas. Na prática o XGBoost não contribui.

**Fazer:**
- [ ] Verificar se é decisão correta da regra de promoção ou sintoma de problema (poucas features úteis, janela de treino curta, limite de 40 mil registros, hiperparâmetros).
- [ ] Testar com janela maior, mais features (por exemplo titularidade e lesões, ver D3) e busca de hiperparâmetros com validação temporal.
- [ ] Se continuar sem ganho, documentar e considerar simplificar o pipeline (remover a camada que não contribui).

### D3. Melhorar a cobertura de dados de entrada
**Problema (da auditoria):** ratings oficiais de times em apenas ~0,26% das linhas; titularidade em ~0,055%; sem boletins históricos de lesões nem escalações confirmadas.

**Fazer:**
- [ ] Executar `scripts/update_advanced_stats.py` e `scripts/update_starter_status.py` de forma incremental até cobrir o histórico disponível.
- [ ] Avaliar uma fonte de lesões históricas e escalações; documentar prós, contras e limites de uso de cada fonte.
- [ ] Medir quanto a cobertura maior melhora o modelo de minutos (hoje a melhoria é de 0,33% sobre a referência).

### D4. Placar dos times: promover o candidato corrigido
**Problema:** o candidato com ratings absolutos e médias de pontos reduziu o erro de placar entre 4% e 6,5% em comparações exploratórias, mas a promoção dependia de corrigir os preenchimentos temporais e repetir a avaliação. O código atual já usa priors fixos e `pregame_scoring_averages`.

**Fazer:**
- [ ] Repetir a avaliação nas três últimas temporadas com a versão corrigida.
- [ ] Se o ganho se mantiver, formalizar a promoção em `reports/model_promotion_*.json` e atualizar `SCORE_MODEL_VERSION` apenas se necessário.

### D5. Calibração do classificador de times
- [ ] Gerar e documentar a calibração por faixas de probabilidade (curva de confiabilidade) para o classificador de vencedor, como a própria auditoria recomenda, e avaliar calibração por regressão isotônica ou Platt, mantendo a que melhorar log loss/Brier em dados fora da amostra.

---

## Bloco E — Robustez operacional (P3)

### E1. Dependência de fontes não oficiais
**Problema:** `nba_api`, ESPN e SportsDataverse podem mudar ou bloquear sem aviso.

**Fazer:**
- [x] Adicionar timeouts e retentativas com espera progressiva nos clientes HTTP, caso ainda não existam (`src/nba_client.py`, `src/live_providers.py`, `src/history_sources.py`).
- [~] Criar um teste de contrato que valida o formato esperado das respostas (com respostas gravadas) para detectar mudança de esquema. — amostras escritas a partir do formato lido pelo código, não gravadas ao vivo (sem rede); trocar por gravações reais
- [x] Exibir na página **Sistema** o estado de cada fonte (última resposta OK e último erro).

### E2. Workflow de gravação diária
- [x] Revisar `.github/workflows/daily-picks.yml`: adicionar notificação ou issue automática quando a execução falhar em sequência (hoje só há upload de artefato). — issue automática; o YAML só roda de verdade no GitHub
- [x] Documentar em `docs/PALPITES_AUTOMATICOS_GITHUB.md` o que fazer quando o cron falha ou a cota do Actions acaba.

### E3. Cobertura de testes
- [x] Adicionar `pytest-cov` ao `requirements-dev.txt`, gerar o relatório de cobertura no CI e definir um piso mínimo realista (medir primeiro, depois fixar). — piso de 70% sobre 72,5% medidos

---

## Ordem de execução sugerida

1. **A1 a A4** (higiene): rápido, sem risco para os modelos.
2. **C4 e C5** (avisos e string fixa): pequenos e isolados.
3. **C1** (exceções e logging).
4. **B** (suporte Linux/macOS).
5. **C2 e C3** (refatorações maiores, um arquivo por vez).
6. **D1 a D5** (modelos e dados), onde a base real estiver disponível.
7. **E1 a E3** (robustez).

## Checklist final

Legenda: [x] feito, [~] parcial, [ ] pendente. Resultado da execução de 08/11/2026 na branch `melhorias/plano-geral`.

- [x] `ruff check .` sem erros
- [x] `mypy` sem erros (Linux e Windows)
- [x] `pytest -q` com todos os testes passando (507 passando, 3 ignorados) e sem avisos de depreciação do projeto
- [x] README curto + `CHANGELOG.md` + `docs/README.md` criados
- [~] Raiz do repositório limpa: sobraram `CRIAR_ATALHO.bat` e `PUBLICAR_GITHUB.bat` (veja A4) e os arquivos de plano
- [x] Nenhuma previsão pré-jogo preservada foi alterada
- [x] Resumo das mudanças e dos itens não concluídos (com motivo) entregue ao final
- [ ] Bloco D (D1 a D5) pendente: exige a base real; comandos em `docs/PENDENCIAS_DADOS_REAIS.md`
