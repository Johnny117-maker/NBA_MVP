# Auditoria dos modelos — 27/10/2026

## Conclusão

Há necessidade de melhorias, com prioridade na validade da avaliação, na qualidade
das entradas e na previsão de placar/minutos. Os testes recentes indicam sinal útil
nos modelos atuais. A melhoria deve ser medida por alvo e por período.

Esta análise usa o código atual, os registros de 21/10/2026, o CSV de backtest
existente e novas comparações. A execução abre o SQLite em modo somente leitura.
Resultados reproduzíveis: [JSON da auditoria](../reports/model_audit_2026-10-27.json).

## Atualização — modelos de zonas

O preenchimento do início das séries em `src/shot_model.py` deixou de usar médias da
base inteira: usa priors fixos por zona (`ZONE_SHARE_PRIOR`, `ZONE_FG_PCT_PRIOR`), e o
teste `test_zone_features_of_past_games_ignore_future_games` reproduz a sonda acima.
O corte treino/teste das zonas e os folds do walk-forward agora mantêm cada data
inteira de um lado só. Os priors são valores aproximados da liga, escritos no código.
As métricas de zonas citadas neste documento foram calculadas antes da correção e
precisam ser recalculadas com a base real (`scripts/retrain_models.py`); este
repositório não inclui a base, então o novo backtest não foi executado.

## Base e entradas

| Item | Situação observada |
| --- | --- |
| Jogos | 9.509, de 16/10/2018 a 12/04/2026 |
| Jogadores por partida | 202.840 registros |
| Arremessos | 1.689.886 tentativas |
| Ratings oficiais de equipe | 50 registros em 25 jogos; cerca de 0,26% das 19.018 equipes-partidas |
| Titularidade preenchida | 112 registros; cerca de 0,055% dos registros de jogadores |

Assim, os ratings de equipe usam principalmente a aproximação por pontos por jogo,
e a titularidade histórica depende majoritariamente da aproximação por minutos.
Ambas estão documentadas no código, mas limitam a interpretação dos fatores.
O histórico também precisa receber os jogos posteriores a abril para acompanhar
mudanças de rotação e equipe. Dados de disponibilidade dos atletas continuam sendo
uma lacuna para prever minutos em um confronto atual.

## Problemas confirmados na validação temporal

Foi executada uma sonda sintética: acrescentar uma partida futura extrema e verificar
se as características anteriores mudam. Uma previsão anterior deve depender apenas
do que já era conhecido naquela data.

| Característica anterior | Antes | Após acrescentar um jogo futuro |
| --- | ---: | ---: |
| `home_off_rating`, primeira partida | 105,00 | 191,25 |
| `fgpct_avg10_Restricted Area`, primeira partida | 0,500 | 0,625 |

As mudanças confirmam preenchimentos com médias da série inteira em
`src/features.py::_add_rolling_features`, `src/shot_model.py::add_zone_rolling_features`
e `add_opponent_zone_defense_features`. É necessário substituir esses preenchimentos
por referências anteriores à data, com um valor neutro fixo no início da série.
O tamanho do efeito sobre o erro real precisa ser medido depois dessa correção.

Os cortes de treino/teste dos modelos de zonas ainda são feitos por posição de
linha. As cinco fronteiras verificadas na base real têm a mesma data dos dois lados,
incluindo 12/01/2025 no corte de 80%. O agrupamento por datas completas já existe
nos modelos de jogadores e deve ser aplicado também a zonas e times.

Essa prioridade segue a [orientação de validação temporal do scikit-learn](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-of-time-series-data).

## Times: classificador e placar têm resultados diferentes

O vencedor usa regressão logística; os placares usam Ridge. A nova avaliação treinou
nas temporadas anteriores e testou cada uma das três temporadas mais recentes por
inteiro, sem pesquisa de hiperparâmetros.

| Temporada de teste | Acerto do vencedor | Sempre escolher mandante | MAE do placar atual, por equipe | Candidato experimental |
| --- | ---: | ---: | ---: | ---: |
| 2023-24 | 63,58% | 54,31% | 10,07 pts | 9,41 pts |
| 2024-25 | 64,90% | 54,45% | 9,87 pts | 9,40 pts |
| 2025-26 | 65,55% | 55,43% | 10,11 pts | 9,69 pts |

O classificador supera essa referência simples nas três temporadas. Em 2025-26,
o Brier é 0,213 contra 0,247 da probabilidade constante estimada no treino.
Isso mostra menor erro probabilístico; a calibração também precisa ser examinada
por faixas de probabilidade. Os dados dessas faixas estão no JSON. A documentação
do [scikit-learn sobre calibração](https://scikit-learn.org/stable/modules/calibration.html)
explica por que Brier e log loss, isoladamente, não separam todos os aspectos da qualidade.

O placar atual usa apenas diferenças entre equipes. Assim, não distingue bem dois
times com produção absoluta alta de dois times com produção absoluta baixa quando
as diferenças entre eles são iguais. Além disso, a diferença de net rating é uma
combinação das diferenças ofensiva e defensiva, gerando redundância.

O candidato mantém Ridge e acrescenta os ratings absolutos das duas equipes e as
médias anteriores de pontuação. O erro de placar caiu entre 4,17% e 6,55% nessas
comparações exploratórias. Os preenchimentos temporais diagnosticados acima ainda
fazem parte da preparação atual: corrigir essa etapa e repetir a avaliação é condição
para promover o candidato.

## Jogadores: teste novo com a janela utilizada nos palpites

A arquitetura combina Ridge para minutos/taxas, HistGradientBoosting para pontos
por minuto e referências da temporada-base. A janela diária tem limite de 40 mil
registros para controlar memória.

O teste novo usou 39.992 registros, com treino em 31.654 linhas de 17/01/2025 a
21/02/2026. O teste contém 8.320 registros com minutos positivos, de 22/02/2026 a
12/04/2026. Nenhuma data aparece nos dois lados desse corte. O modelo foi ajustado
somente no treino; as referências e previsões usam informação anterior a cada jogo.

| Alvo | MAE do modelo | MAE da referência | Melhoria observada |
| --- | ---: | ---: | ---: |
| Minutos | 5,12 | 5,14 | 0,33% |
| Pontos | 4,68 | 4,92 | 4,83% |
| Rebotes | 1,91 | 1,95 | 2,03% |
| Assistências | 1,39 | 1,44 | 3,43% |

Para minutos, a referência é a média recente já disponível antes do jogo. Para os
demais alvos, é a taxa da temporada-base multiplicada pelos mesmos minutos previstos
usados pelo modelo. Também foram calculadas referências com taxas e minutos recentes;
os resultados completos estão no JSON. Menor MAE significa menor erro absoluto médio.
O resultado mede produção quando há atuação, e não a probabilidade de o atleta participar.

Pontos, rebotes e assistências superaram as referências nesse teste, com ganhos
moderados. A previsão de minutos quase empatou com a referência: melhorar oportunidade,
rotação, ausências e titularidade é uma prioridade. Um único período não comprova
que o ganho se repetirá em outra temporada.

### Por que o relatório antigo parecia pior em rebotes

O último registro informa MAE de rebotes 2,55 contra 1,96 da referência sazonal,
mas o CSV revela grande diferença entre folds. O primeiro modelo treina em apenas
283 registros de duas datas, depois prevê de 18/10/2018 a 19/01/2020. Nesse bloco,
o MAE de rebotes é 5,09; nos quatro blocos seguintes fica entre 1,88 e 1,93.

Esse início curto e o longo período sem reajuste não representam o uso diário atual.
O protocolo precisa de um aquecimento suficiente e uma frequência de retreino
compatível com a aplicação. Convém publicar resultados por temporada, perfil e
volume de minutos, além da média geral. Os logs antigos usam média simples dos
folds, enquanto a média sobre todas as linhas dá pesos diferentes.

## Arremessos: interpretar corretamente a métrica

O MAE registrado de 2,72 pontos é de **pontos de bola de quadra, usando FGA real**
na avaliação. Essa métrica isola a distribuição/eficiência por zona e não inclui
o erro de prever o volume de tentativas nem os lances livres. Por isso, não é
comparável diretamente ao MAE de pontos do modelo de jogadores.

As prioridades são corrigir os preenchimentos e cortes temporais, acrescentar
referências simples por zona e depois avaliar a cadeia completa com FGA previsto.
Nesta auditoria, a avaliação de zonas foi inspecionada e reproduzida nas sondas;
não foi executado um novo backtest sobre os 1,69 milhão de arremessos.

## Ordem recomendada de melhoria

1. Corrigir os preenchimentos que consultam o futuro e unificar os cortes por data.
2. Atualizar os dados e medir cobertura de ratings, titulares e disponibilidade.
3. Validar o placar com variáveis absolutas em novas janelas temporais.
4. Melhorar minutos e comparar cada alvo com referências simples, por temporada.
5. Alinhar treino offline e janela diária; registrar versão do código, período,
   tamanho da amostra e limites dos intervalos junto de cada avaliação.

O retreino offline ainda tenta preparar a base completa e pode repetir os problemas
de memória já observados. O limite diário de 40 mil registros não é aplicado pelo
script antigo de retreino. A calibração dos intervalos deve ser feita com previsões
fora da amostra e verificada em um período posterior, com cobertura por perfil.

## Reprodução

```powershell
.venv\Scripts\python.exe scripts\audit_models.py --players --as-of 2026-10-27 --output reports\model_audit_2026-10-27.json
```

Esse comando gera a auditoria sem gravar novos modelos ou registros de treinamento.
O experimento de placar fica no auditor; a aplicação mantém o treinamento existente.
