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

## Como ler cada palpite

A explicação mostra o limite exato de contagem: na linha 20,5, Over é 21 ou mais
e Under é 20 ou menos; na linha 20, há empate em exatamente 20. A frequência dos
dez jogos anteriores e a média da temporada são contexto, não probabilidades novas.
Somente jogos anteriores e do próprio atleta entram nesse contexto preservado.

As novas capturas registram o peso efetivamente usado de Bayes e XGBoost e a
correção posterior pelos resultados. A soma das parcelas reproduz a projeção.
Essa conta explica a combinação dos modelos, sem atribuir efeito causal a descanso,
defesa ou outra variável. Capturas antigas sem esses campos indicam a limitação.
Quando o peso do XGBoost é zero, a explicação informa que ele não participa do valor.

O erro do método no teste agregado não é uma comprovação para o jogador individual.
A disponibilidade, o marcador e eventuais restrições de minutos ainda dependem de
informações confirmadas. O total cedido pela equipe adversária não é a previsão
individual do atleta.

## Validação específica de Over e Under

O ajuste de dispersão usa uma grade fixa de multiplicadores e é escolhido somente
no bloco interno de calibração. Só é habilitado quando reduz Brier em pelo menos
0,0015 e 1% tanto na calibração quanto em datas internas posteriores, sem piorar
log loss além de 0,001. Cada bloco precisa ter 400 atletas/jogos e 14 datas.
Se o ajuste de minutos estiver ativo, essa correção de dispersão aguarda uma
avaliação conjunta. Correções de média por feedback também não reutilizam uma
calibração de dispersão incompatível.

As janelas externas ficam fora dessa seleção e mostram o resultado real da política.
A grade usa a linha de referência, cinco pontos abaixo/acima para PTS e duas unidades
para REB/AST, sempre em meia unidade. Linhas repetidas são removidas. Várias linhas
da mesma partida não são observações independentes e não aumentam a quantidade de
jogos de atletas. Over e Under são complementares nessas linhas: não contam como
duas evidências. Linhas inteiras têm empate separado e não entram no Brier binário.

O sistema também testa que Over + Under + empate soma um, que aumentar a linha
reduz a chance de Over e que uma média zero não produz contagem positiva. A linha
original preserva a probabilidade capturada, mesmo após atualizações do cálculo.
Probabilidades ao vivo e linhas de casas não estão certificadas por esse teste.

## Comando de reprodução

```powershell
.venv\Scripts\python.exe scripts\validate_player_props.py --db data\nba.db --before-day 2026-11-03 --output reports\validation\props_validation.json
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
