# Histórico diário e modelos de player props

## Previsões preservadas

A tela **Histórico diário** registra a primeira previsão disponível de cada jogo do dia NBA
(fuso America/New_York), antes do horário de início. O coletor escolhe até três destaques de
cada equipe pela produção recente e guarda PTS, REB, AST, minutos esperados, faixas P10–P90,
referências Over/Under, estimativas Bayes e XGBoost, versão do modelo e horário de captura.
A seleção exige histórico recente e não confirma escalação nem disponibilidade médica.

Os registros ficam em `data/nba_analysis.sqlite`, separados do histórico de treino e do
placar ao vivo. Triggers impedem UPDATE e DELETE de previsões pela aplicação. Um SHA-256
verifica a integridade do conteúdo. Novas consultas, retreinos e resultados não substituem
a fotografia original. Não se criam previsões retroativas para jogos já iniciados.

O resultado é associado à data, mandante, visitante e ID canônico do jogador. A aplicação
mantém as revisões do resultado em uma tabela separada. Atletas sem participação não são
avaliados como se tivessem uma previsão errada de zero pontos. Resultados ausentes aguardam
boxscore suficiente. Correções são verificadas durante 14 dias; previsões ainda não resolvidas
também são buscadas em ciclos posteriores, em lotes de até 200 jogos.

O HTML para impressão é salvo automaticamente em `data/analyses/AAAA-MM-DD/` e também pode
ser baixado pela tela. Abra o HTML e use Ctrl+P para imprimir ou salvar PDF. A comparação pode
ser exportada como CSV e o registro integral como JSON. O HTML conserva somente a previsão
original, independentemente dos resultados posteriores.

Os registros sobrevivem ao fechamento do programa. Para capturar novos dias automaticamente,
o servidor precisa permanecer executando. Bases, modelos treinados e relatórios individuais
ficam localmente e são ignorados pelo Git; preservá-los em outro computador exige copiar
esses arquivos. O GitHub recebe código e relatórios agregados, não o arquivo diário pessoal.

## Modelos locais

- **Gamma-Poisson:** posterior de taxa por minuto com exposição recente e prior explícito;
  distribuição binomial negativa para contagens, com sobredispersão por partida. A incerteza
  da taxa e a variabilidade por partida são combinadas. As faixas continuam experimentais.
- **Beta-Binomial:** estabilização das conversões de três pontos e lances livres. Os priors
  declarados são 36% e 78%, com força equivalente a 50 tentativas; não são médias atuais
  da liga calculadas com dados futuros.
- **Filtro dinâmico local:** aproximação gaussiana sobre o log da taxa por minuto, com ruído
  dependente da amostra. Não é DARKO/DPM.
- **XGBoost:** três regressores `count:poisson`, um para PTS, REB e AST. Usa 30 características
  de minutos, descanso, casa/fora, forma, eficiência, uso e contexto do adversário. A seleção
  de atletas não usa o resultado da partida alvo. Os modelos antigos de outras páginas
  permanecem identificados nas respectivas análises.

O treino usa até 40 mil observações recentes, preservando datas completas. Todas as features
usam apenas datas anteriores à partida, inclusive estatísticas de colegas e adversários.
IDs, minutos efetivamente jogados no alvo e resultado do próprio dia não são features.

As datas são divididas em treino inicial (60%), calibração (20%) e teste (20%). O peso de
XGBoost na combinação é escolhido somente na calibração, entre 0%, 25%, 50%, 75% e 100%.
Exige ganho de pelo menos 1% de MAE nesse bloco; caso contrário, conserva 0% de ML e mostra
separadamente a estimativa XGBoost. O bloco de teste é usado para relatar o erro, sem escolher
os pesos. Depois, os modelos de produção são ajustados em todo o histórico anterior ao alvo.
Modelos são persistidos em JSON com hash dos dados e manifesto. Um tick de placar não retreina.

Na execução real de 28/10/2026, o modelo teve 36.569 observações elegíveis e 7.867 no teste:

| Estatística | MAE Bayes | MAE XGBoost | Peso ML escolhido na calibração |
| --- | ---: | ---: | ---: |
| PTS | 4,873 | 4,864 | 0% |
| REB | 1,946 | 1,953 | 0% |
| AST | 1,419 | 1,421 | 0% |

O ganho mínimo de calibração não foi atingido. Não foi promovido um modelo com base apenas
na sua complexidade ou na pequena diferença de PTS observada no teste. MAE de projeções
centrais não comprova calibração das probabilidades Over/Under, retorno financeiro ou
vantagem contra cotações reais. As linhas automáticas são referências estatísticas.

## Métricas e dependências

| Indicador | Implementação disponível | Limite dos dados atuais |
| --- | --- | --- |
| TS% | Pontos divididos por 2 × (FGA + 0,44 × FTA) | Denominador zero gera ausência |
| USG% | Estimativa com boxscores completos dos jogadores | Pode omitir eventos registrados apenas para a equipe |
| AST Ratio / TOV Ratio | Por 100 posses individuais estimadas | São diferentes de AST/TO |
| RAPM | Ridge esparso sobre stints, ponderado pelas posses | Exige dez IDs distintos e posses medidas; sem stints reais importados nesta entrega |
| LEBRON | Importação de valores publicados com fonte Basketball Index | Nenhum valor proprietário foi reconstruído ou importado nesta entrega |
| DARKO DPM | Importação de valores publicados com fonte DARKO | O filtro dinâmico local não recebe o nome DARKO |
| xP de localização | XGBoost para probabilidade de acerto × valor da tentativa | Sem distância do defensor, velocidade ou relógio de posse |
| Gravity local | Aproximação defensiva fora da bola, ponderada pela duração | Exige tracking externo, defensor atribuído e referência espacial |
| DFG% a menos de 6 pés | `nba_api.LeagueDashPtDefend`, categoria `Less Than 6Ft` | Endpoint inacessível nesta rede; nenhuma observação foi fabricada |

RAPM e Gravity são cálculos funcionais sobre os contratos de entrada descritos no laboratório.
Os CSVs podem ser enviados pela tela para calcular e baixar os resultados. O RAPM exibe alpha
e exposição; esse alpha não é apresentado como ajustado automaticamente à liga. O Gravity
local mede diferença de distância em pés e não é um índice oficial universal de gravidade.

Os valores publicados são contexto externo com `as_of`, fonte e `known_at` (horário de
importação). Eles não são usados retroativamente como features de treino. Uma data de
referência antiga não prova que o projeto conhecia o valor naquela época.

O coletor de defesa faz uma tentativa pública por dia, usando corte até o dia anterior;
há também um botão manual no laboratório. PBP e rotações oficiais podem ser coletados via
CLI para auditoria. O projeto não converte substituições incompletas em posses inventadas.

O xP foi treinado em 60 mil tentativas anteriores ao dia alvo, com corte temporal. O teste
obteve Brier 0,2286, contra 0,2497 da taxa geral do treino, e log loss 0,6487. O histórico de
arremessos disponível termina em 12/04/2026; não representa tracking ou forma de arremesso
coletada na temporada 2026–27. Essa limitação aparece no manifesto do laboratório.

## Operação

Abra `INICIAR_PROJETO.bat`. O inicializador verifica Streamlit e XGBoost e instala as
dependências ausentes. O monitor continua enquanto o servidor existir, com ou sem a aba aberta.

Comandos opcionais na raiz do projeto:

```powershell
.\.venv\Scripts\python.exe scripts/archive_daily.py
.\.venv\Scripts\python.exe scripts/archive_daily.py --train-only
.\.venv\Scripts\python.exe scripts/archive_daily.py --shot-quality
.\.venv\Scripts\python.exe scripts/archive_daily.py --rapm-game 0022600001
```

O último comando exige um ID oficial de jogo válido e acessível; o ID acima ilustra o formato.
O CLI compartilha a trava do monitor e não executa uma segunda coleta concorrente.

Para importar indicadores publicados: CSV com `metric,player_id,as_of,value,source`.
Os IDs devem ser oficiais NBA e a fonte de LEBRON/DARKO deve apontar ao produtor.

Para RAPM: `home_players,away_players,points_diff,possessions`, com escalações em listas JSON.
Para Gravity: `frame_id,player_id,ball_handler_id,x,y,defender_x,defender_y,baseline_distance,duration`;
coordenadas em pés e duração em segundos. Não há tracking óptico individual na base atual.

## Referências primárias

- [Basketball Index — LEBRON Introduction](https://www.bball-index.com/lebron-introduction/)
- [DARKO — metodologia e limites](https://beta.darko.app/about)
- [NBA — glossário](https://www.nba.com/stats/help/glossary)
- [nba_api — LeagueDashPtDefend](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguedashptdefend.md)
- [nba_api — ShotChartDetail](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/shotchartdetail.md)
- [XGBoost — parâmetros e objetivos](https://xgboost.readthedocs.io/en/stable/parameter.html)

Validação local desta entrega: 341 testes aprovados, Ruff e mypy para Linux/Windows.
Testes cobrem congelamento, corte temporal, correções de resultado, integridade, fórmulas,
provedor de defesa, fontes publicadas, xP, RAPM, Gravity e todas as telas do projeto.
