# Melhorias na previsão de pontos dos jogadores

## O que foi alterado

- As divisões treino/teste e o backtest agora usam datas completas. Linhas da mesma data não podem ficar dos dois lados da divisão.
- Os preenchimentos de médias da liga foram substituídos por médias históricas calculadas apenas com datas anteriores. Quando não há histórico anterior, são usados priors fixos documentados no código.
- O fallback de defesa adversária deixou de usar a média de toda a série histórica, evitando olhar para partidas futuras.
- As características de jogadores agora contêm médias recentes de 3/5/10 jogos, taxas por minuto, uso ofensivo, eficiência, minutos, titularidade aproximada, troca de equipe e descanso.
- A geração dessas características foi vetorizada; no banco histórico incluído, o conjunto de 202.840 registros foi preparado em cerca de 12 segundos no ambiente de validação.
- A projeção central de pontos usa `HistGradientBoostingRegressor` para pontos por minuto multiplicados pelos minutos previstos. A cadeia FGA × TS% permanece como alternativa explicável, não como fórmula da previsão central.
- As métricas passaram a comparar o modelo direto, a cadeia FGA × TS% e uma referência simples baseada na taxa recente de pontos por minuto.
- A tela de projeção e a tela de qualidade foram atualizadas para explicar a diferença entre as previsões.
- A complexidade dos modelos de quantis foi reduzida (árvores rasas e 60 estimadores) para melhorar regularização e tempo de execução.

## Backtest temporal com o banco incluído

Execução com dados reais de `data/nba.db`, 202.840 registros de jogador-partida e três folds temporais. O conjunto de teste de cada fold contém datas posteriores às usadas no treino.

| Métrica de pontos | MAE médio dos 3 folds |
|---|---:|
| Modelo direto (previsão principal) | 4,619 pontos |
| Cadeia FGA × TS% | 4,688 pontos |
| Referência: taxa recente × minutos previstos | 4,837 pontos |

No backtest utilizado, o modelo direto reduziu o MAE em aproximadamente 1,5% contra a cadeia FGA × TS% e 4,5% contra a referência simples. Esses valores descrevem apenas esta base e este desenho de avaliação; devem ser recalculados após atualizações dos dados.

A cobertura média do intervalo normal em pontos foi aproximadamente 82,3% nos três folds, perto do alvo nominal de 80%.

## Limitações que continuam

- As métricas de pontos são calculadas somente em partidas em que o jogador registrou minutos. Não há ainda um modelo separado de disponibilidade/lesão pré-jogo.
- `is_starter` continua parcialmente ausente; a feature usa a aproximação documentada baseada em minutos relativos à equipe quando o dado oficial não existe.
- Não foram incluídos dados pré-jogo confirmados de lesão, escalação ou restrição de minutos. Esses sinais não devem ser inventados a partir do resultado da própria partida.
- O teste completo da aplicação Streamlit não foi possível neste ambiente por ausência da dependência `streamlit`; os testes isolados de features, métricas e modelos de jogador passaram.

## Testes executados

- `37 passed` nos testes isolados de `test_player_features.py`, `test_player_metrics.py` e `test_player_model.py`.
- Compilação sintática dos módulos de Python modificados.
- Backtest temporal de três folds no banco histórico incluído.
