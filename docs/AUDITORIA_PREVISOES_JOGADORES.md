# Auditoria das previsões de jogadores

## Objetivo

Medir erros de minutos, pontos, rebotes e assistências fora da amostra e evitar
que uma projeção seja avaliada contra uma partida diferente daquela pretendida.

## Mudanças

- A previsão de minutos combina o regressor do projeto com um prior de rotação
  calculado a partir dos minutos recentes, minutos no stint atual e média da
  temporada anterior. A participação do stint cresce com o número de jogos
  observados no time atual.
- A confiança usa o erro residual histórico de minutos, pontos, rebotes e
  assistências, junto com a quantidade de histórico do jogador e a estabilidade
  do stint. As classes Alta/Média/Baixa são heurísticas de incerteza, não
  probabilidades de acerto.
- O backtest walk-forward retorna resultados jogador-partida com data, fold,
  equipe, adversário, previsão, valor real e erros absolutos/assinados.
- `python scripts/retrain_models.py` salva o relatório em
  `reports/player_backtest_predictions.csv`. A aplicação apresenta métricas por
  rodada/data e por jogador, além de permitir baixar o CSV.
- Novas previsões registram a data-alvo escolhida. A resolução compara somente
  com a partida nessa data e verifica adversário/mando quando a base dispõe
  desses campos. Registros antigos migram automaticamente; sem data-alvo, o
  sistema tenta casar adversário e mando antes de usar o próximo jogo.
- A página Desempenho apresenta MAE de minutos, pontos, rebotes e assistências
  por rodada e compara o erro observado entre classes de confiança.

## Como usar

1. Atualize os dados reais antes de avaliar.
2. Execute `windows/RETREINAR_MODELOS.bat` no Windows ou `python scripts/retrain_models.py` no terminal.
3. Abra **Qualidade do Modelo** para examinar MAE por rodada e por jogador.
4. Gere novas previsões na página **Jogadores**, selecione a data exata do jogo,
   equipe adversária e mando, e registre a previsão.
5. Depois da coleta de resultados do jogo, abra **Desempenho** e clique em
   **Resolver previsões com jogos reais**.
6. Exporte `nba_player_prediction_audit.csv` para análise adicional.

## Interpretação

- MAE mede o erro absoluto médio: menor é melhor.
- Viés é previsão menos valor real; positivo indica superestimação.
- O relatório walk-forward testa cada grupo de datas usando modelos treinados
  apenas com dados anteriores a esse grupo.
- Partidas com zero minutos/DNP não estão incluídas na avaliação de pontos,
  rebotes e assistências; modelar a probabilidade de jogar é uma melhoria futura.
- Dados ausentes de lesões, status pré-jogo ou rotação esperada limitam o teto
  de precisão do sistema.
- Os relatórios são locais e não versionados no Git porque dependem dos dados
  coletados em cada instalação.
