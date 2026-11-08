# NBA Analytics Lab

Aplicação em Python (Streamlit) para analisar jogadores e times da NBA, projetar jogos do dia e
acompanhar a qualidade das próprias previsões ao longo da temporada.

> **Importante:** este projeto **não prevê o prêmio de MVP da NBA**. O nome do repositório
> (`NBA_MVP`) é histórico. O foco são projeções de pontos, rebotes e assistências de jogadores,
> probabilidade de vitória e placar de times, sempre com avaliação contra os resultados reais.
> As probabilidades são experimentais e não são recomendação de aposta.

## O que o projeto faz

- **Times:** probabilidade de vitória e placar projetado, com força dos times por Elo
  (com margem de vitória e regressão à média entre temporadas) e modelo Ridge de margem e total
  de pontos. Detalhes em [docs/MODELO_TIMES_ELO.md](docs/MODELO_TIMES_ELO.md).
- **Jogadores:** projeção de PTS, REB e AST por jogo, com intervalos de incerteza, eficiência
  (TS%, eFG%, USG%), mapa de arremessos por zona, defesa e marcações.
- **Jogos e palpites do dia:** capturas pré-jogo preservadas com horário, versão do modelo e
  hash SHA-256, comparadas depois com o resultado real (página **Histórico diário**).
- **Qualidade dos modelos:** validação cronológica, calibração e auditoria dos erros.
- **Atualização diária:** coleta os jogos finalizados do dia anterior e os jogos novos
  ([docs/ATUALIZACAO_DIARIA.md](docs/ATUALIZACAO_DIARIA.md)).

![Fluxo da análise de jogadores](docs/material/Analise_Jogadores_diagrama.png)

## Requisitos

- Python 3.12
- Acesso à internet para coletar dados via `nba_api`
- Windows, Linux ou macOS (os atalhos `.bat` são só para Windows)

## Instalação

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    |    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Para desenvolvimento (testes, lint e tipos), use `requirements-dev.txt`.
No Windows, `windows/INSTALAR_DEPENDENCIAS.bat` faz esses passos.

## Como executar

```bash
python -m streamlit run app.py
```

No Windows também é possível usar `windows/INICIAR_PROJETO.bat`. Na primeira execução não há dados
reais: colete-os pela página **Dados e atualizações** ou com os scripts abaixo.

## Dados e scripts principais

Os dados ficam em `data/` (banco SQLite `data/nba.db`, que **não** é versionado).

| Script | Função |
|---|---|
| `python scripts/sync_current_season.py` | Sincroniza a temporada atual |
| `python scripts/update_daily.py` | Atualização diária (jogos de ontem e de hoje) |
| `python scripts/collect_history.py` | Coleta de histórico de temporadas |
| `python scripts/retrain_models.py` | Retreina os modelos |
| `python scripts/audit_models.py` | Auditoria de modelos contra jogos ainda não vistos |

## Testes e qualidade

```bash
python -m ruff check .
python -m mypy src pages app.py desktop_launcher.py scripts
python -m pytest -q
```

O workflow `tests.yml` roda os mesmos comandos no GitHub Actions.

## Documentação

- [Guia detalhado](docs/GUIA_DETALHADO.md): funcionalidades, páginas e funcionamento interno.
- [Histórico de mudanças](CHANGELOG.md): versões e correções.
- [docs/](docs/): documentos técnicos de cada modelo e processo.
- [Executável para Windows](docs/EXECUTAVEL_WINDOWS.md): geração e uso do pacote `.exe`.
- [Plano de melhorias](PLANO_DE_MELHORIAS.md): tarefas de organização e qualidade.

## Aviso

Dados e previsões têm fins de estudo. Os modelos erram, e a qualidade medida em jogos passados
não garante desempenho futuro.
