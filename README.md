# NBA Analytics Lab

MVP educacional para análise de jogos e comparação de times da NBA. O projeto treina modelos simples com dados históricos, calcula probabilidades experimentais, projeta pontuações e explica os fatores mais relevantes.

> A base incluída é sintética e não representa a temporada atual. O projeto não utiliza odds e não oferece orientação de apostas.

## Funcionalidades da versão 0.1

- Comparação entre dois times;
- Probabilidade experimental de vitória;
- Projeção de placar e intervalo de incerteza;
- Forma recente;
- Explicação dos fatores do modelo;
- Simulação de 5.000 cenários;
- Métricas de validação cronológica;
- Upload de uma base própria em CSV;
- Coleta de jogos reais via `nba_api`, salvos em SQLite;
- Página de jogadores: eficiência (TS%, eFG%, USG%, AST/TO), estatísticas
  por 36 minutos, consistência e comparador de 2 a 4 jogadores;
- Simulação de Monte Carlo de temporada: probabilidade de classificação
  direta, Play-In e playoffs por time;
- Projeção de desempenho de jogadores: minutos, pontos, rebotes e
  assistências do próximo jogo, com intervalo de incerteza;
- Índice NAPS (0-100, por percentil) e classificação automática de estilo
  de jogo por regras;
- Offensive/Defensive Rating oficiais de times (coleta incremental jogo a
  jogo), com aproximação por pontos como reserva;
- Registro permanente de previsões de times, comparação com o resultado
  real e histórico de retreinamento dos modelos.

## Tecnologias

- Python;
- Streamlit;
- Pandas e NumPy;
- Scikit-learn;
- Plotly;
- Pytest.

## Estrutura

```text
nba-analytics/
├── .streamlit/
│   └── config.toml
├── pages/
│   ├── 1_Jogadores.py
│   ├── 2_Temporada.py
│   └── 3_Desempenho.py
├── scripts/
│   ├── retrain_models.py
│   ├── update_advanced_stats.py
│   ├── update_data.py
│   └── update_starter_status.py
├── src/
│   ├── __init__.py
│   ├── data.py
│   ├── features.py
│   ├── model.py
│   ├── nba_client.py
│   ├── nba_teams.py
│   ├── player_data.py
│   ├── player_features.py
│   ├── player_index.py
│   ├── player_metrics.py
│   ├── player_model.py
│   ├── season_simulator.py
│   ├── simulation.py
│   └── store.py
├── tests/
│   ├── test_app.py
│   ├── test_data.py
│   ├── test_features.py
│   ├── test_model.py
│   ├── test_player_data.py
│   ├── test_player_features.py
│   ├── test_player_index.py
│   ├── test_player_metrics.py
│   ├── test_player_model.py
│   ├── test_players_page.py
│   ├── test_season_simulator.py
│   ├── test_store.py
│   ├── test_store_advanced.py
│   ├── test_store_players.py
│   └── test_store_predictions.py
├── app.py
├── requirements.txt
└── README.md
```

## Como executar no Windows

Abra o terminal do VS Code dentro da pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

O navegador normalmente abrirá em:

```text
http://localhost:8501
```

Se o PowerShell bloquear a ativação do ambiente virtual, execute apenas nesta sessão:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Como executar os testes

```powershell
pytest -q
```

## Como coletar dados reais

O script abaixo baixa jogos reais da NBA via `nba_api` e salva em um banco
SQLite local (`data/nba.db`), sem duplicar jogos em execuções repetidas:

```powershell
python scripts/update_data.py
```

Por padrão ele baixa as três últimas temporadas regulares
(`2022-23`, `2023-24`, `2024-25`). Para escolher outras:

```powershell
python scripts/update_data.py --seasons 2023-24 2024-25
```

Depois de rodar o script, selecione "Dados reais (coletados)" na barra
lateral do app. Essa fonte depende de acesso à internet até `stats.nba.com`;
se a coleta falhar por timeout ou bloqueio, tente novamente mais tarde.

### Offensive/Defensive Rating oficiais

Por padrão, `off_rating`/`def_rating` são uma aproximação: a média móvel de
pontos marcados/sofridos nos últimos 10 jogos de cada time. Um script
separado baixa o Rating oficial da NBA (Offensive/Defensive Rating de
verdade, via `BoxScoreAdvancedV3`) jogo a jogo:

```powershell
python scripts/update_advanced_stats.py --seasons 2023-24
```

Esse endpoint exige **uma chamada por jogo** (diferente da coleta de times/
jogadores, que é uma chamada por temporada inteira) — é lento e, com
milhares de jogos já coletados, pode levar bastante tempo. Por isso a
coleta é incremental e retomável: cada execução baixa até `--limit` jogos
(padrão 200) que ainda não têm Rating oficial e para; rode o comando de
novo (quantas vezes quiser, inclusive em dias diferentes) para continuar de
onde parou. Times/jogos ainda não cobertos continuam usando a aproximação
por pontos automaticamente — nada quebra por faltar dado oficial, a
previsão só fica um pouco menos precisa até a coleta avançar.

> A aproximação por pontos continua sendo o comportamento padrão até você
> rodar `update_advanced_stats.py`. Isso é suficiente para o MVP, mas o
> Rating oficial, quando coletado, é mais preciso.

O mesmo `python scripts/update_data.py` já coleta o boxscore de todos os
jogadores da temporada (uma chamada por temporada, igual à coleta de
times) e alimenta a página "Jogadores".

## Página de jogadores

Acesse pela barra lateral do Streamlit ("Jogadores"). Funciona com a base
demonstrativa (jogadores sintéticos, sem relação com atletas reais) ou com
os dados reais coletados pelo `update_data.py`. Três abas:

- **Visão geral**: ranking por produção, com filtro por time;
- **Perfil individual**: estatísticas tradicionais, eficiência
  (TS%, eFG%, USG%, AST/TO), consistência (média, desvio-padrão,
  coeficiente de variação, percentis 25/75) e evolução recente de pontos e
  minutos;
- **Comparação**: 2 a 4 jogadores lado a lado.

> `USG%` é calculado sem uma tabela de estatísticas de time separada: os
> totais do time em cada jogo (tentativas de arremesso, lances livres,
> turnovers e minutos) são obtidos somando o boxscore de todos os
> jogadores daquele time naquele jogo. É uma aproximação — eventos
> registrados só para a equipe (não atribuídos a nenhum jogador) não
> entram nessa soma.
>
> A lista de jogadores também não usa uma tabela `players` separada: nome
> e time atual são derivados diretamente do histórico de jogos, o mesmo
> princípio já usado para a lista de times.

Na aba "Perfil individual", filtros de **período, casa/fora, adversário e
minutos mínimos** recortam as métricas, a tabela de consistência e os
gráficos de pontos/minutos por jogo — sem coleta nova, tudo derivado das
colunas que já existem em `player_game_stats`. Os gráficos também marcam
com uma linha tracejada cada data de troca de time
(`team_stint_id`/`assign_team_stints`, a mesma detecção de troca usada nos
modelos). Os filtros afetam só essa visualização: os modelos de projeção
(aba "Projeções", abaixo) continuam usando o histórico completo do
jogador para calcular as médias móveis — filtrar os dados de treino por um
recorte pequeno pioraria a previsão, não ajudaria.

Uma quarta aba, **Projeções**, prevê o próximo jogo de um jogador (como
descrito no planejamento de sabermetria), com intervalo de incerteza baseado
no erro histórico de cada modelo — o mesmo princípio do `predict_game` de
times. Minutos vêm de um modelo próprio; rebotes e assistências são
produção por minuto (minutos × taxa). **Pontos são decompostos em volume ×
eficiência**, em vez de uma taxa única "pontos por minuto":

```text
minutos previstos
  × arremessos por minuto previstos (modelo de volume — FGA)
  = FGA previstos
  × proporção histórica FTA/FGA do próprio jogador (razão, não modelo)
  = FTA previstos

TS% previsto (modelo de eficiência — já usa a força do adversário)
  × 2 × (FGA previstos + 0,44 × FTA previstos)
  = pontos previstos
```

Separar volume de eficiência evita misturar duas coisas diferentes numa
taxa só: "jogou mais e arremessou mais" (volume) reage a minutos e ao
próprio ritmo do jogador; "arremessou igual, mas acertou mais" (eficiência)
é o que reage à força do adversário. A aba mostra os três números da cadeia
(minutos, FGA, TS%) junto com o resultado final. Mostra também o mando de
quadra, os dias de descanso e o erro médio absoluto (MAE) de cada modelo.

Os dois modelos reconhecem **troca de time**: cada jogador tem uma
"passagem" (`team_stint`, `src/player_features.py::assign_team_stints`) por
time, detectada automaticamente a partir do histórico já coletado (sem
precisar de nenhuma coleta nova). As médias existem em duas versões —
carreira inteira e só a passagem atual — e `games_since_trade` diz há
quantos jogos o jogador está no time atual. O modelo (Ridge) aprende sozinho
quanto pesar cada uma; nos primeiros jogos depois de uma troca, sem
histórico na passagem nova, a versão "da passagem" cai automaticamente na
média de carreira.

As médias (carreira e passagem) são **médias móveis exponenciais**, não uma
janela flat: o jogo mais recente pesa mais do que um jogo de 10 partidas
atrás, em vez de os dois pesarem igual. Duas velocidades — `_avg5` (reage
rápido a uma sequência quente/fria) e `_avg10` (forma mais estável) —, com
a mesma fórmula usada tanto no treino quanto na previsão ao vivo.

O Usage Rate (USG%) recebe o mesmo tratamento — `usg_pct_avg10` (carreira) e
`usg_pct_avg10_stint` (passagem atual), entrando no modelo de volume (FGA)
junto com a taxa de arremessos por minuto: USG% alto é outro jeito de captar
"a bola passa mais pela mão desse jogador", útil sobretudo logo depois de uma
troca de time, quando a função ofensiva pode mudar antes mesmo dos minutos
ou dos arremessos por minuto se estabilizarem.

A aba também tem um seletor de **próximo adversário**: a força defensiva do
time escolhido (`opponent_def_rating`, média expansiva de pontos sofridos
por esse time até a data de cada jogo histórico, sem vazamento) entra nos
modelos de pontos/rebotes/assistências — jogar contra uma defesa fraca
projeta mais produção do que contra uma forte.

Uma última seção, **Probabilidade de over/under**, deixa escolher uma
estatística (pontos, rebotes ou assistências) e um "line" de referência, e
calcula a probabilidade de a produção real do jogador superar esse valor
(`src/player_model.py::over_probability`). O cálculo aproxima o erro do
modelo por uma distribuição normal centrada na previsão, com desvio-padrão
igual ao erro histórico (`residual_std`) daquela estatística: quanto mais
longe o line está da previsão em unidades desse erro, mais a probabilidade
se afasta de 50%.

> Essa probabilidade é uma leitura estatística do próprio modelo, não uma
> odds de mercado — o mesmo `residual_std` agregado (não calibrado por
> jogador) usado nos intervalos de incerteza da seção anterior, então um
> astro muito consistente e um jogador irregular têm a mesma largura de
> incerteza nessa primeira versão. O projeto não utiliza odds nem oferece
> orientação de apostas.

Logo abaixo, **Distribuição de resultados** generaliza a mesma ideia: em vez
de um único line, mostra a probabilidade em 5 faixas
(`src/player_model.py::range_probabilities`), no espírito de "até 19 / 20–24
/ 25–29 / 30–34 / 35 ou mais" em vez de só acima/abaixo de um número. A
largura das faixas não é fixa — é o erro histórico do modelo arredondado
(mínimo 1), centrada na própria previsão, para fazer sentido tanto para
pontos quanto para rebotes/assistências e tanto para um astro quanto para um
jogador de banco.

O modelo de minutos também usa `starter_rate_avg10`/`_stint`: a taxa recente
de titularidade (titular ou reserva) do jogador. Coletar titularidade real
exige um endpoint por jogo (`BoxScoreTraditionalV3`,
`scripts/update_starter_status.py`), então é coleta incremental e lenta,
igual ao Rating oficial. Enquanto um jogo não tem titularidade coletada, o
projeto aproxima: jogador com minutos acima da mediana do time naquele jogo
é tratado como "provável titular"
(`src/player_features.py::effective_starter_flag`) — mesmo espírito da
aproximação por pontos usada para o Rating oficial antes da coleta oficial
chegar. Nada quebra por titularidade ausente; a previsão só fica um pouco
menos precisa até a coleta avançar.

```powershell
python scripts/update_starter_status.py --seasons 2023-24
```

> O modelo de minutos ainda **não** tem acesso a informações de lesões ou
> disponibilidade dos companheiros, fatores citados no planejamento original
> que ainda não são coletados por este projeto.
>
> `player_game_stats.team`/`.opponent` guardam a sigla do time (ex.: "PHI"),
> diferente de `games.home_team`/`away_team`, que guardam o nome completo —
> formatos diferentes de dois endpoints da própria `nba_api`. O contexto do
> adversário faz essa tradução por uma tabela de siglas
> (`src/nba_teams.py::TEAM_ABBREVIATION_TO_NAME`); os demais campos de
> jogador (nome exibido, comparações) continuam mostrando a sigla.

### Índice NAPS e estilo de jogo

Na "Visão geral", a tabela traz colunas de **NAPS** (0-100, ordenável) e
**Estilo**. No "Perfil individual", um radar mostra os percentis por
dimensão do jogador selecionado. Só entram no ranking jogadores
**qualificados**: pelo menos 15 jogos e 10 minutos de média — quem não
atinge o mínimo aparece nas outras abas normalmente, mas sem NAPS/estilo.

O NAPS é uma média ponderada de percentis (calculados entre os jogadores
qualificados, não a liga inteira) em seis dimensões:

| Dimensão | Peso | Baseado em |
|---|---:|---|
| Eficiência ofensiva | 25% | TS%, eFG% |
| Criação de jogadas | 20% | AST%, AST/TO |
| Defesa (proxy) | 15% | Roubos + bloqueios por 36 min |
| Rebotes | 15% | REB% |
| Consistência | 15% | Coeficiente de variação de pontos (invertido) |
| Disponibilidade | 10% | Jogos disputados |

AST% e REB% usam as fórmulas oficiais (basketball-reference): como a coleta
traz o boxscore de **todos** os jogadores de ambos os times em cada jogo, os
totais do time e do adversário são obtidos somando essas linhas — o mesmo
princípio já usado para USG%.

A classificação de **estilo** (Criador principal, Armador organizador,
Pontuador de volume/eficiente, Especialista de três, Ala 3-and-D, Protetor
de aro, Reboteiro, Defensor de perímetro, Reserva de impacto ou Jogador
versátil) é feita por uma cascata de regras sobre esses mesmos percentis
(≥70 = "alto", ≤30 = "baixo"), não por Machine Learning — o próprio
planejamento trata clusterização como evolução futura.

> O planejamento original pede sete dimensões, incluindo "Impacto coletivo"
> (net rating do time com o jogador em quadra vs. fora). Essa dimensão
> **não está no NAPS**: calculá-la exige dados de stint/play-by-play (saber
> o placar enquanto cada jogador está em quadra), que este projeto não
> coleta. O peso dela foi redistribuído entre as demais dimensões.
>
> A "Defesa" é uma aproximação simples por contagem (roubos + bloqueios por
> 36 minutos), não o Defensive Rating em quadra nem o DFG% oficiais.
>
> Os percentis **não são segmentados por posição** (a coleta atual não traz
> posição do jogador) — um pivô é comparado com armadores no mesmo grupo.
> É a limitação mais visível desta primeira versão: um pivô defensivo
> tende a ter "Criação de jogadas" mais baixa só por jogar uma função
> diferente, não por ser pior jogador.
>
> O NAPS é um índice **experimental** do projeto — não é uma medida oficial
> nem absoluta de qualidade de um jogador.

## Simulação de temporada

Acesse pela barra lateral do Streamlit ("Temporada"). Exige dados reais
coletados (não tem base demonstrativa: os jogos sintéticos são pares de
times sorteados aleatoriamente, sem um calendário de temporada real de
verdade para dividir em "conhecido" e "a simular"). Escolha uma temporada já completa no banco e
uma data de corte — jogos antes do corte contam como resultado real
conhecido; jogos depois do corte viram o calendário a simular (usa-se
apenas os confrontos e datas reais, **não** o placar real). O sistema roda
milhares de simulações de Monte Carlo do restante da temporada usando o
mesmo modelo de vitória já treinado (`src/model.py`), incluindo o
mini-mata-mata oficial do Play-In (7º x 8º e 9º x 10º colocados).

Duas abas:

- **Probabilidades**: por conferência, projeção de vitórias finais (com
  intervalo P10–P90) e probabilidade de classificação direta, Play-In e
  playoffs por time;
- **O que realmente aconteceu**: como os jogos depois do corte já
  aconteceram de verdade, mostra a classificação real da temporada regular
  lado a lado com a probabilidade simulada — uma forma de validar visualmente
  a qualidade da simulação.

> Simplificações desta primeira versão: a força de cada time (net rating,
> forma, eficiência) fica **congelada** no momento do corte — não é
> recalculada a cada jogo simulado dentro de uma mesma simulação. Empates no
> número de vitórias são resolvidos pelo net rating do time (não pelos
> critérios oficiais de desempate da NBA, como confronto direto). E como o
> projeto só coleta jogos de temporada regular, o painel de revelação mostra
> a faixa de posição real (direta/Play-In/fora), não o resultado real dos
> jogos do Play-In em si.

## Formato do CSV

O arquivo precisa conter estas colunas:

```text
game_date
home_team
away_team
home_off_rating
away_off_rating
home_def_rating
away_def_rating
home_net_rating
away_net_rating
home_last10_win_pct
away_last10_win_pct
home_rest_days
away_rest_days
home_points
away_points
```

Cada linha representa uma partida. As variáveis de rating, forma e descanso precisam refletir apenas informações conhecidas **antes do jogo**, evitando vazamento de dados.

## Como o modelo funciona

1. Os jogos são ordenados por data.
2. Os primeiros 80% treinam um modelo de avaliação.
3. Os 20% finais medem o desempenho em dados futuros.
4. Uma regressão logística estima a probabilidade de vitória.
5. Dois modelos Ridge projetam as pontuações.
6. Depois da avaliação, os modelos finais são treinados com toda a base.

## Desempenho do modelo

Na página inicial, depois de gerar uma previsão de times, o botão
**"Registrar esta previsão"** salva um snapshot (times, probabilidade,
placar previsto, confiança) em SQLite. Acesse "Desempenho" pela barra
lateral para acompanhar:

- **Previsões registradas**: tabela de tudo que foi salvo, com o botão
  "Resolver previsões com jogos reais" — procura, na base de jogos já
  coletada, o primeiro jogo real entre os mesmos dois times (na mesma
  ordem mandante/visitante) depois da data em que a previsão foi
  registrada. Quando encontra, preenche o placar real e calcula o erro;
  quando não encontra (o confronto ainda não aconteceu de novo, ou nunca
  vai — são times escolhidos livremente pelo usuário, não uma agenda real
  de jogos futuros), a previsão continua pendente. Isso é esperado, não é
  um erro.
- **Histórico de treinamento**: cada vez que `python
  scripts/retrain_models.py` roda, ele grava accuracy/log loss/Brier
  score/MAE (times) e MAE de minutos/pontos/rebotes/assistências
  (jogadores) em uma tabela de log, com gráfico de evolução ao longo do
  tempo.

O modelo de jogadores é avaliado por **validação walk-forward**
(`src/player_model.py::walk_forward_evaluate`), não um único split 80/20:
os jogos são ordenados por data e divididos em 5 janelas sucessivas — a
primeira janela treina com o começo da base e avalia no trecho seguinte, a
segunda treina com tudo até ali (incluindo o trecho já avaliado) e avalia
no próximo trecho, e assim por diante até o fim da base. O MAE final é a
média das 5 janelas. Isso testa o modelo em vários pontos do tempo, com
tamanhos de treino crescentes, em vez de uma única divisão fixa — mais
fiel a como o modelo seria usado de verdade (treinar com o que já
aconteceu, prever o que vem a seguir) e menos sensível a uma divisão que
por acaso caiu num trecho fácil ou difícil da temporada.

### Intervalos por regressão quantílica (opcional, ainda não é o padrão)

Por padrão, os intervalos de incerteza de pontos/rebotes/assistências
assumem que o erro do modelo segue uma Normal (mesma aproximação usada no
over/under e na distribuição por faixa da página de jogadores). Como
alternativa experimental, `train_player_models(..., interval_method="quantile")`
treina três `GradientBoostingRegressor` por estatística (percentis 10/50/90)
em vez de assumir uma forma de erro simétrica — em teoria, mais fiel à
distribuição real (chão perto de zero, cauda longa para cima em noites
excepcionais). A previsão central (pontos/rebotes/assistências mostrados na
tela) **não muda** — só de onde vem o intervalo. Como três modelos de quantil
treinados de forma independente não têm garantia de não se cruzar, o
intervalo final sempre passa por um `min`/`max` de segurança.

`walk_forward_evaluate(..., interval_method=...)` também reporta a
**cobertura do intervalo** (fração de jogos reais que caiu dentro do
intervalo previsto — num intervalo de ~80% bem calibrado, deveria ficar
perto de 0,80) para os dois modos poderem ser comparados de verdade antes de
decidir trocar o padrão. Rodando contra os dados reais já coletados
(walk-forward de 2 janelas, mesma base de 202.840 linhas das outras
verificações desta fase):

| Modo | Cobertura pts | Cobertura reb | Cobertura ast |
|---|---:|---:|---:|
| `normal` | 0,73 | 0,73 | 0,73 |
| `quantile` | 0,68 | 0,79 | 0,90 |

O resultado **não** aponta um vencedor claro: `quantile` chegou mais perto
de 0,80 em rebotes e passou de 0,80 em assistências (intervalo mais largo
que o necessário), mas ficou pior que `normal` em pontos — justamente a
estatística mais importante da tela. Também confirma algo que vale registrar
por si só: o intervalo `normal` de hoje está um pouco **estreito demais**
nas três estatísticas (cobertura na casa de 0,73, não 0,80) — o erro real
tem cauda mais gorda do que uma Normal pura previa. Por esses dois motivos —
sem vitória clara do modo quantílico e um problema de calibração que
precisaria de mais investigação de qualquer forma — **`"normal"` continua
sendo o padrão** usado pelo app e pelo script de retreinamento; ajustar a
calibração (ex.: um multiplicador maior que 1,28, ou recalibrar por
estatística) fica como próximo passo antes de revisitar o modo quantílico.

> Números exatos variam por execução (a base real continua crescendo a cada
> coleta) — rode o comando acima com os dois modos para ver o resultado mais
> recente. O modo quantílico também é bem mais caro para treinar
> (`GradientBoostingRegressor` em vez de Ridge, 3 modelos por estatística em
> vez de 1: ~2 minutos para 2 janelas nesta comparação, contra ~1 segundo do
> modo normal) — mais um motivo para não ser o padrão de cada carregamento
> da página.

```powershell
python scripts/retrain_models.py
```

> "Retreinamento automático" aqui significa um script que treina os
> modelos com os dados mais recentes e grava as métricas — este projeto
> não tem um processo de fundo rodando sozinho. Para rodar
> periodicamente, agende o comando acima no Agendador de Tarefas do
> Windows (`taskschd.msc` → Criar Tarefa Básica → apontar para o `python`
> do `.venv` com o script como argumento).
>
Jogadores têm o mesmo mecanismo: na aba "Projeções" (página "Jogadores"), o
botão **"Registrar esta previsão"** salva minutos/pontos/rebotes/
assistências previstos, a confiança e o adversário escolhido (guardado só
como contexto). Na aba "Previsões de jogadores" de "Desempenho", o botão
"Resolver previsões com jogos reais" casa cada previsão com o **próximo
jogo real do mesmo jogador** — diferente da resolução de times, não exige
que o adversário real seja o mesmo escolhido na previsão, porque ali o
adversário é hipotético (não vem de uma agenda real de jogos futuros);
exigir esse casamento deixaria quase tudo pendente para sempre.

## Próximas versões

- [x] Conector com `nba_api`;
- [x] Banco SQLite e atualização incremental;
- [x] Offensive/Defensive Rating oficiais (coleta incremental via `BoxScoreAdvancedV3`, com aproximação por pontos como reserva enquanto a coleta não cobre todos os jogos);
- [x] Estatísticas reais dos 30 times na base demonstrativa (offense/defense calibrados pela média real de pontos da temporada 2024-25; pace estimado, sem Rating oficial pace-ajustado para os 30 ainda; os jogos em si continuam simulados);
- [x] Módulo de jogadores (primeira versão: game logs, eficiência, per-36, consistência, comparador);
- [x] Índice próprio (NAPS) e estilo de jogo (primeira versão: sem segmentação por posição, sem impacto on/off, defesa por proxy simples);
- [x] Previsão de minutos, pontos, rebotes e assistências (primeira versão: sem dados de lesões/escalação do adversário);
- [x] Simulação de classificação, Play-In e playoffs (primeira versão: força congelada no corte, sem critérios oficiais de desempate);
- [x] Registro permanente das previsões (times e jogadores, registro manual por botão, resolução sob demanda contra jogos reais já coletados — para jogadores, a resolução casa pelo próximo jogo real do jogador, não pelo adversário hipotético escolhido);
- [x] Retreinamento automático (script `scripts/retrain_models.py` + histórico de métricas; agendamento da execução periódica fica a cargo do usuário);
- [x] Trajetória do jogador (segunda versão): passagem por time (`team_stint`), contexto do adversário (força defensiva), médias móveis exponenciais, decomposição de pontos em volume × eficiência e validação walk-forward para o log de métricas do modelo de jogadores;
- [x] Probabilidade por faixa e Usage Rate por passagem no modelo de pontos;
- [x] Filtros de período/casa-fora/adversário/minutos e marcador de troca de time na página de jogadores;
- [x] Coleta de titularidade (titular/reserva) via `BoxScoreTraditionalV3`, incremental e lenta como o Rating oficial, com aproximação por minutos acima da mediana do time enquanto não coletada;
- [x] Intervalos por regressão quantílica (opcional, `interval_method="quantile"`): alternativa ao intervalo Normal, comparável via cobertura no `walk_forward_evaluate`; `"normal"` continua sendo o padrão do app.

