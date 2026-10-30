# Comprovação da qualidade das previsões

## Dois tipos de evidência

**Capturas pré-jogo** compara somente previsões preservadas antes do início da
partida e com corte de dados anterior ao dia do jogo. Registros sem proveniência
verificável ficam fora das métricas. Ausências não viram produção zero.

**Teste histórico independente** reconstrói previsões em duas janelas sucessivas,
com 14 datas de jogos em cada uma. O treino e todas as escolhas de peso e minutos
terminam antes da janela externa. O modelo fica congelado; as médias de forma
podem incorporar partidas anteriores à previsão, inclusive dentro da janela.
Esse teste não cria capturas retroativas no histórico diário.

## Comparações e critérios

- MAE: erro absoluto médio, comparado à média das dez partidas anteriores na mesma amostra.
- Viés: previsto menos realizado; positivo significa superestimação.
- Faixa P10–P90: cobertura observada, com referência nominal de 80%; contagens inteiras podem ampliá-la.
- Intervalo de 95% do ganho: bootstrap pareado por partida, com 1.000 reamostragens.
- Brier e log loss: qualidade das probabilidades, comparada também à frequência de Over
  aprendida apenas no período anterior ao teste. Brier inferior a 0,25, isoladamente,
  não comprova vantagem.

A indicação de evidência histórica favorável para produção exige pelo menos 500
observações, 30 partidas, 14 datas, redução de MAE de pelo menos 2% e intervalo do
ganho inteiramente positivo. Esses limiares são uma regra do projeto, não uma
certificação estatística universal. A dependência entre partidas do mesmo atleta
pode permanecer mesmo agrupando os atletas de cada partida no bootstrap.

O teste usa atletas com pelo menos cinco observações anteriores e dez minutos
esperados, considerando apenas quem efetivamente participou. Não avalia a capacidade
de prever participação. As linhas são referências estatísticas do sistema, não linhas
reais de casas. Não há backtest de lucro, boletins históricos de lesões nem escalações
confirmadas nesse teste.

## Reprodução

```powershell
.venv\Scripts\python.exe scripts\validate_player_props.py --db data\nba.db --before-day 2026-10-30 --output reports\validation\props_validation.json
```

O JSON informa versão, impressão digital dos dados, cortes temporais, amostra,
resultados por temporada e SHA-256 do CSV de casos. O CSV permite conferir cada
jogador, partida, projeção, linha e resultado. Ambos são artefatos de avaliação;
não alteram as previsões originais. O resumo público acompanha a distribuição em
`docs/validation/props_validation.json`; modelos novos incorporam seu próprio teste
independente ao manifesto.

As métricas internas de desenvolvimento continuam visíveis no Laboratório,
identificadas como internas. Elas não substituem o teste externo nem a avaliação
prospectiva das capturas reais. Resultados agregados não comprovam qualidade para
um atleta específico ou desempenho futuro.

Referências: [calibração e regras de pontuação, scikit-learn](https://scikit-learn.org/stable/modules/calibration.html)
e [distribuição binomial negativa, SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.nbinom.html).
