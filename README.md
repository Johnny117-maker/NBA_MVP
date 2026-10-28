# NBA Analytics Lab

Aplicativo de análise da NBA com histórico local, atualização da temporada, projeções de jogadores e comparação entre previsões e resultados.

## Executável para Windows

Extraia o pacote `NBAAnalyticsLab-1.1.0-Windows-x64.zip` inteiro e abra
`NBAAnalyticsLab.exe`, mantendo a pasta `_internal` junto dele. O sistema abre em
janela própria e inclui Python, navegador e bibliotecas. Não precisa de servidor
externo. Os dados ficam em `%LOCALAPPDATA%\NBAAnalyticsLab`; a internet é usada para
consultar novos dados. Fechar a janela encerra o processamento.

Execute `CRIAR_ATALHO.bat` para criar o ícone **NBA Analytics Lab** na Área de Trabalho.

Para gerar uma nova versão, use `GERAR_EXECUTAVEL.bat` no ambiente de desenvolvimento.
[Uso, backup, migração e compilação](docs/EXECUTAVEL_WINDOWS.md).

> Os dados reais são coletados após a instalação; exemplos sintéticos servem para demonstração e testes. A disponibilidade ao vivo depende das fontes e da rede. As probabilidades são experimentais; cotações externas são opcionais.

## Defesa e marcações por jogador

**Defesa dos times** compara DRtg, perímetro, pontos no garrafão cedidos e regiões
de arremesso, com fonte, data e cobertura. **Marcações e encaixes** mostra os
defensores enfrentados por partida e o desempenho contra perfis defensivos
pré-jogo, com ajuste por minutos e intervalos de incerteza.

O acervo público desde 2022 inclui boxscores, eventos, posses, tracking, hustle,
escalações e matchups. A disponibilidade de marcações atuais depende da publicação
pela NBA. [Fontes, definições e coleta](docs/DEFESA_MARCACOES_E_ACERVO.md).

## Histórico diário e modelos Bayes + XGBoost

O monitor preserva as primeiras projeções pré-jogo dos destaques de cada equipe, com PTS,
REB, AST, intervalos, horário e versão do modelo. Abra **Histórico diário** para consultar,
imprimir e comparar com os resultados. O servidor precisa estar aberto para registrar novos dias.

O **Laboratório de modelos** reúne treino temporal de XGBoost, estimativas bayesianas,
TS%/USG%/AST Ratio/TOV Ratio, xP por localização e ferramentas para RAPM, Gravity e importação
de indicadores publicados LEBRON/DARKO. As métricas que dependem de dados ainda ausentes
aparecem com seus requisitos. [Funcionamento, validação e limites](docs/HISTORICO_DIARIO_E_MODELOS.md).

## Funcionalidades da versão 0.2

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
  real e histórico de retreinamento dos modelos;
- **Mapa de arremessos**: coleta de arremessos via `ShotChartDetail`, mapa
  de pontos/calor/hexagonal, volume e eficiência por zona, comparação entre
  temporadas/times/adversário com explicação automática em linguagem
  natural, e modelo de previsão de distribuição/eficiência por zona com
  validação walk-forward;
- Jogos do Dia: calendário NBA com alternativas SportsDataverse/GitHub e ESPN, cartões de jogadores
  em destaque como primeira aba, filtros por produção/perfil e acesso ao histórico individual;
  probabilidades pelo mesmo modelo da página Times; calendário salvo e cadastro
  manual de confrontos para continuar a análise durante falhas de conexão;
- Palpites de Hoje: jogos ainda não iniciados, preferência do modelo de Times, placar e fatores;
  projeções de pontos/rebotes/assistências dos destaques sob demanda e exportação dos confrontos em CSV.
  Consulte [critérios e limites](docs/PALPITES_E_DESTAQUES.md).
- Interface organizada em 10 telas (Visão Geral, Times, Jogadores, Mapa
  de Arremessos, Temporada, Desempenho, Qualidade do Modelo e Dados e
  Atualizações, Jogos do Dia e Palpites de Hoje), com sistema de design compartilhado (`src/ui/`): selos de
  fonte/atualização, estados padronizados de vazio/erro/amostra pequena,
  seletores com preferência salva na URL e coleta incremental de dados
  reais direto pela interface, sem precisar do terminal.

## Tecnologias

A revisão de interface, com navegação agrupada, controles para
celular e análises sob demanda, está descrita em
[UI e UX — 27/10/2026](docs/UI_UX_2026-10-27.md).

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
│   ├── 0_Times.py
│   ├── 1_Jogadores.py
│   ├── 2_Temporada.py
│   ├── 3_Desempenho.py
│   ├── 4_Mapa_Arremessos.py
│   ├── 5_Dados_Atualizacoes.py
│   ├── 6_Qualidade_Modelo.py
│   ├── 7_Jogos.py
│   └── 8_Palpites.py
├── scripts/
│   ├── retrain_models.py
│   ├── update_advanced_stats.py
│   ├── update_data.py
│   ├── update_shots.py
│   └── update_starter_status.py
├── src/
│   ├── __init__.py
│   ├── court_chart.py
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
│   ├── shot_connector.py
│   ├── shot_features.py
│   ├── shot_model.py
│   ├── shot_storage.py
│   ├── simulation.py
│   ├── store.py
│   └── ui/
│       ├── __init__.py
│       ├── components.py
│       ├── explanations.py
│       ├── formatters.py
│       ├── states.py
│       └── theme.py
├── tests/
│   ├── test_app.py
│   ├── test_court_chart.py
│   ├── test_data.py
│   ├── test_data_updates_page.py
│   ├── test_features.py
│   ├── test_model.py
│   ├── test_model_quality_page.py
│   ├── test_player_data.py
│   ├── test_player_features.py
│   ├── test_player_index.py
│   ├── test_player_metrics.py
│   ├── test_player_model.py
│   ├── test_players_page.py
│   ├── test_season_simulator.py
│   ├── test_shot_connector.py
│   ├── test_shot_features.py
│   ├── test_shot_model.py
│   ├── test_shot_storage.py
│   ├── test_shots_page.py
│   ├── test_store.py
│   ├── test_store_advanced.py
│   ├── test_store_players.py
│   ├── test_store_predictions.py
│   ├── test_times_page.py
│   ├── test_ui_components.py
│   ├── test_ui_explanations.py
│   └── test_ui_formatters.py
├── EXECUTAR_TESTES.bat
├── INICIAR_PROJETO.bat
├── INSTALAR_DEPENDENCIAS.bat
├── app.py
├── requirements.txt
└── README.md
```

A página inicial (`app.py`) é a **Visão Geral**: um painel com cartões de
resumo da base (jogos, times, jogadores, temporadas, arremessos), selo de
fonte/atualização e atalhos para as demais páginas. A comparação de times
em si — o que antes vivia em `app.py` — foi movida para `pages/0_Times.py`,
mantendo a separação de responsabilidades da navegação (seção 3 do
[planejamento de UI/UX](planejamento_ui_ux_nba_analytics.md)).

## Execucao rapida no Windows com arquivos .bat

Na pasta raiz do projeto ha tres atalhos para facilitar o uso:

1. `INSTALAR_DEPENDENCIAS.bat` — cria o ambiente virtual `.venv`, atualiza o `pip` e baixa/instala todos os pacotes listados em `requirements.txt`. Execute este arquivo primeiro se quiser preparar o projeto manualmente.
2. `INICIAR_PROJETO.bat` — inicia o Streamlit e abre o navegador. Se o ambiente virtual ou o Streamlit ainda nao estiver instalado, chama automaticamente o instalador de dependencias.
3. `EXECUTAR_TESTES.bat` — executa a suite automatizada com `pytest`.

**Antes de comecar:** extraia o ZIP inteiro para uma pasta local; nao execute os arquivos de dentro do ZIP. E necessario ter Python instalado (preferencialmente Python 3.12) e acesso a internet para baixar os pacotes. O arquivo `.bat` instala as bibliotecas Python, mas nao instala o proprio Python nem atualiza automaticamente os dados da NBA.

Para uso normal, basta dar duplo clique em `INICIAR_PROJETO.bat`. Mantenha a janela aberta enquanto estiver usando a aplicacao. Para parar o servidor, volte a essa janela e pressione `Ctrl+C`.

O BAT abre **http://localhost:8501** automaticamente quando o servidor fica pronto.
Se este projeto já estiver usando a porta 8501, o auxiliar
`scripts/prepare_start.ps1` confirma os processos e reinicia essa instância para
carregar os arquivos atuais. Outros programas na mesma porta são preservados;
nesse caso, o atalho explica o conflito e encerra a inicialização.
Abrir o projeto não dispara um novo treinamento completo dos modelos.

Para verificar a inicialização sem encerrar o servidor nem abrir o navegador,
execute `INICIAR_PROJETO.bat --verificar` no terminal.

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

## Auditar o treinamento

A temporada atual agora é sincronizada automaticamente ao abrir o projeto.
A Visão Geral mostra oportunidades estatísticas de Over/Under e a nova tela
**Over / Under ao vivo** permite acompanhar boxscores e analisar uma linha de
pontos, rebotes ou assistências. As fontes públicas funcionam sem cadastro;
conexões ao vivo dependem da disponibilidade da NBA/ESPN nesta rede.
Veja [fontes, configuração, limites e validação](docs/ATUALIZACAO_AUTOMATICA_E_AO_VIVO.md).
Para atualizar uma vez sem abrir o navegador, execute `ATUALIZAR_TEMPORADA.bat`.

A [auditoria de 27/10/2026](docs/AUDITORIA_MODELOS_2026-10-27.md) compara modelos e
referências simples, verifica dependências temporais e descreve as prioridades de melhoria.
Para gerar uma nova avaliação local, com até 40 mil registros de jogadores:

```powershell
python scripts/audit_models.py --players
```

O resultado fica em `reports/model_audit.json`. A auditoria consulta o banco em modo
somente leitura e mantém os modelos e o histórico de treinamentos existentes.

O modelo de placar v2 usa ataque, defesa e pontuação recente de cada equipe,
além das diferenças entre os times. A [validação da ativação](docs/MODELO_PLACAR_V2.md)
registra a comparação com o modelo anterior em três temporadas completas.
Para treinar e registrar apenas os modelos de times, com o ambiente virtual ativado:

```powershell
python scripts/retrain_models.py --team-only
```

## Publicar no GitHub

O arquivo `PUBLICAR_GITHUB.bat` cria um commit e publica a **branch atual** no remoto `origin`. Em uma pasta sem Git, inicializa a branch `main`; em um repositório existente, preserva a branch selecionada. Antes de executá-lo:

1. Instale o [Git para Windows](https://git-scm.com/download/win).
2. Crie no GitHub um repositório **vazio**, sem gerar README, `.gitignore` ou licença automaticamente.
3. Execute `PUBLICAR_GITHUB.bat`: confira a branch, o status e o resumo dos arquivos exibidos. Se já houver arquivos preparados com `git add`, somente esses arquivos serão incluídos; caso contrário, o script prepara as alterações respeitando o `.gitignore`. Quando houver alterações preparadas, pede a mensagem do commit. A URL só é solicitada se `origin` ainda não estiver configurado.
4. Escreva uma mensagem curta que descreva a mudança, por exemplo `Melhora previsao de pontos e minutos`, e pressione Enter. A mensagem é usada no commit do Git; se não houver alterações staged, nenhum commit novo será criado.
5. Conclua a autenticação do GitHub pelo Git Credential Manager ou pelo método de autenticação configurado no Git. Não coloque tokens ou senhas no código nem nos arquivos `.bat`.

O projeto inclui `.github/workflows/tests.yml`: o GitHub Actions executa Ruff,
mypy e pytest automaticamente em novos pushes e pull requests.

Para mudanças incrementais, prefira mensagens que descrevam uma entrega concreta:
`feat: adiciona calendario gratuito`, `fix: corrige filtro de jogadores` ou
`docs: atualiza instrucoes de execucao`. Registre cada etapa concluída e validada.

Antes do envio, o BAT consulta o remoto. Se houver commits novos no GitHub, para
e orienta a integrá-los por merge ou rebase. O commit local permanece salvo;
o script não renomeia branches existentes, não resolve conflitos automaticamente
e não usa push forçado. Conflitos já pendentes e detached HEAD impedem a execução.

### Por que o banco de dados não vai para o GitHub?

O arquivo local `data/nba.db` não é incluído no repositório, pois a base histórica pode ser muito grande para um arquivo Git comum e muda conforme as coletas. O `.gitignore` mantém bancos SQLite, ambientes virtuais, caches e modelos treinados fora do versionamento. A pasta `data/` fica representada por `data/.gitkeep`.

Após clonar o projeto, é possível abrir a aplicação em modo demonstrativo e coletar dados reais pela página **Dados e Atualizações** ou pelos scripts em `scripts/`. A coleta real depende de conexão com a internet e dos serviços da NBA.

> **Atenção à licença:** este repositório não adiciona uma licença de código aberto em seu nome. Antes de publicar publicamente, escolha e adicione um arquivo `LICENSE` se desejar conceder permissões específicas de reutilização.


Os testes de `persistent_selectbox` verificam `st.query_params`, a API atual do
Streamlit. Quando um parâmetro contém um único valor, o acesso
`app.query_params["chave"]` retorna uma `str` (por exemplo, `"Ana"`), não uma
lista como acontecia com a API antiga `st.experimental_get_query_params`.

## Lint e checagem de tipos

```powershell
ruff check .
mypy src pages app.py scripts
```

`tests/` fica fora do escopo obrigatório do `mypy` (configurado em
`pyproject.toml`): os stubs do `AppTest` do Streamlit devolvem tipos amplos
demais para o filtro feito em runtime nos testes de página, e algumas
fixtures sintéticas (dicts aninhados literais) colapsam para tipos genéricos
— ruído de inferência, não bug. `src/`, `pages/`, `app.py` e `scripts/`
(código de produção) ficam 100% cobertos.

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

### Arremessos (mapa de arremessos)

Baixa os arremessos de cada jogador via `ShotChartDetail` e alimenta a
página "Mapa de Arremessos":

```powershell
python scripts/update_shots.py
```

Assim como o Rating oficial, é **uma chamada por jogador por temporada** —
lento, então a coleta é incremental e retomável (`--seasons`, `--limit`,
`--delay`); rode de novo quantas vezes quiser para continuar de onde
parou. Um jogador com zero arremessos de quadra na temporada (ponta de
banco, contrato two-way) sempre aparece como "pendente" — é o
comportamento esperado, não uma falha, e não vale a pena tentar de novo.

Também dá para coletar lotes pequenos (jogos de uma temporada inteira, ou
até ~30 jogadores de arremessos por vez) direto pela página **"Dados e
Atualizações"** da barra lateral, com barra de progresso — sem precisar do
terminal. Coletas grandes continuam melhor pelo terminal em segundo plano.

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
produção por minuto (minutos × taxa). Para pontos, a previsão central usa um
**regressor direto de pontos por minuto** (`HistGradientBoostingRegressor`)
vezes os minutos projetados, com histórico recente, uso ofensivo, volume,
eficiência, contexto e uma referência da temporada-base. A cadeia FGA × TS%
continua calculada como referência interpretável e é comparada no backtest:

```text
Modelo híbrido principal:
  (1 - peso anual) × previsão dinâmica
  + peso anual × taxa da temporada-base × minutos previstos

Referência interpretável:
  FGA previstos × TS% previsto × proporção histórica FTA/FGA
  → estimativa alternativa de pontos
```

As características incluem médias recentes dos últimos 3/5/10 jogos,
minutos e uso ofensivo, eficiência, passagem atual pelo time, descanso,
mando de quadra e defesa adversária. Os preenchimentos da liga usam apenas
datas anteriores. A avaliação divide partidas por datas completas, não por
linhas, e compara o modelo híbrido à cadeia FGA × TS%, à referência simples
(taxa recente de pontos × minutos previstos) e às médias da temporada-base
adaptadas aos minutos previstos. A interface mostra essas métricas para não
presumir que um modelo complexo é sempre melhor. A métrica
de pontos é condicional a o jogador ter registrado minutos na partida; lesões
e probabilidade pré-jogo de participação ainda não são modeladas.

Os modelos de minutos, pontos e volume/eficiência reconhecem **troca de time**: cada jogador tem uma
"passagem" (`team_stint`, `src/player_features.py::assign_team_stints`) por
time, detectada automaticamente a partir do histórico já coletado (sem
precisar de nenhuma coleta nova). As médias existem em duas versões —
carreira inteira e só a passagem atual — e `games_since_trade` diz há
quantos jogos o jogador está no time atual. Os modelos Ridge de minutos,
volume e eficiência aprendem quanto pesar cada uma; o modelo direto de pontos
usa árvores rasas com regularização. Nos primeiros jogos depois de uma troca, sem
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

### Referência da temporada anterior (PTS, REB e AST)

As projeções agora usam também a média da temporada-base mais recente para **pontos, rebotes, assistências e minutos**, além das respectivas taxas por minuto. Para uma linha de `2025-26`, por exemplo, as features de referência são calculadas exclusivamente a partir da temporada `2024-25` do mesmo jogador, com partidas de todos os times somadas quando houve uma troca no meio do ano. Isso dá ao modelo um ponto de partida estável sem assumir que a produção vai continuar igual automaticamente.

A projeção final combina o modelo dinâmico com a taxa da temporada-base ajustada para os minutos previstos. O peso inicial da temporada-base é de até 60% no primeiro jogo de uma nova passagem pelo time; cai 4 pontos percentuais a cada jogo dessa passagem, até o mínimo de 20% após dez jogos. Esse peso é reduzido quando há menos de dez partidas históricas disponíveis para sustentar a média. Assim, o modelo pode acompanhar mudanças de papel, minutos, volume de arremessos e criação de jogadas, sem abandonar completamente o desempenho anterior.

A página **Projeções** mostra a temporada usada como referência e compara a média por jogo de PTS/REB/AST com a estimativa para o próximo jogo. A página **Qualidade do Modelo** também registra o MAE da referência anual, para avaliar se o ajuste pelo modelo melhora ou piora a previsão em relação a simplesmente manter a taxa da temporada-base. Se um jogador mudar de equipe antes de disputar uma partida pelo novo time, o projeto ainda não consegue inferir sozinho a nova função: precisa que os dados da troca/novo time sejam atualizados ou de uma entrada explícita dessa informação.

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

## Mapa de arremessos

Acesse pela barra lateral do Streamlit ("Mapa de Arremessos"). Exige
arremessos coletados (`python scripts/update_shots.py` ou a página "Dados e
Atualizações") — não tem base demonstrativa, arremesso é um dado espacial
que não faz sentido sintetizar. Cinco abas:

- **Mapa de pontos**: cada arremesso na posição em que aconteceu, verde
  (convertido) ou vermelho (errado);
- **Mapa de calor**: concentração de tentativas (`Histogram2d` — um
  histograma 2D discreto, não um contorno suavizado, que interpolaria
  entre clusters distantes de dados e sugeriria volume onde não há
  nenhum arremesso);
- **Mapa hexagonal**: tamanho do hexágono = volume de tentativas, cor =
  pontos por tentativa numa escala divergente centrada na referência de
  liga (vermelho acima, azul abaixo);
- **Por zona**: tabela de volume/eficiência por zona com suavização
  bayesiana do FG% (`shrunk_fg_pct`) — protege contra amostra pequena,
  ex.: 3 de 4 não é tratado como 75% de verdade;
- **Comparações**: duas temporadas, primeiros × últimos N jogos, ou contra
  um adversário específico (defesa por zona derivada dos arremessos já
  coletados, sem tabela nova no banco), com uma explicação automática em
  linguagem natural do que mudou (`src/ui/explanations.py`);
- **Projeções**: distribuição prevista de arremessos por zona e FG%
  esperado por zona, treinados com um Ridge por zona (participação e
  eficiência) sobre os jogos de todos os jogadores já coletados — mesma
  arquitetura EWMA sem vazamento e defesa por adversário com média
  expansiva já usada no modelo de jogadores. Minutos e FGA continuam vindo
  do modelo de jogadores (aba "Projeções" de "Jogadores"); este modelo só
  decompõe o FGA em zona × eficiência. Validado por walk-forward: o MAE de
  pontos de bola-de-quadra fica bem abaixo do MAE de prever a média
  constante (ver "Qualidade do Modelo").

> Free throw fica de fora inteiramente: o `ShotChartDetail` só traz
> arremessos de quadra (`context_measure_simple="FGA"`). O índice NAPS, a
> defesa por zona e a referência de liga usam só os jogadores já
> coletados nesta base, não a liga inteira — ficam mais confiáveis
> conforme mais jogadores forem coletados.

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

O histórico de retreinamento (accuracy/log loss/Brier/MAE ao longo do
tempo, para os três modelos) mudou para a página **"Qualidade do Modelo"**
— ver seção abaixo.

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
# Windows
double-click RETREINAR_MODELOS.bat

# Or in PowerShell
python scripts/retrain_models.py
```

> "Retreinamento automático" aqui significa um script que treina os
> modelos com os dados mais recentes e grava as métricas — este projeto
> não tem um processo de fundo rodando sozinho. Para rodar
> periodicamente, agende o comando acima no Agendador de Tarefas do
> Windows (`taskschd.msc` → Criar Tarefa Básica → apontar para o `python`
> do `.venv` com o script como argumento).
>
> O script avalia os três modelos (times, jogadores e — se houver
> arremessos coletados — zonas de arremesso, também por validação
> walk-forward) e grava tudo na mesma tabela de histórico, lida pela
> página "Qualidade do Modelo".

Jogadores têm o mesmo mecanismo: na aba "Projeções" (página "Jogadores"), o
botão **"Registrar esta previsão"** salva minutos/pontos/rebotes/
assistências previstos, a confiança e o adversário escolhido (guardado só
como contexto). Na aba "Previsões de jogadores" de "Desempenho", o botão
"Resolver previsões com jogos reais" casa cada previsão com o **próximo
jogo real do mesmo jogador** — diferente da resolução de times, não exige
que o adversário real seja o mesmo escolhido na previsão, porque ali o
adversário é hipotético (não vem de uma agenda real de jogos futuros);
exigir esse casamento deixaria quase tudo pendente para sempre.

## Qualidade do Modelo

Acesse pela barra lateral do Streamlit ("Qualidade do Modelo") — erros,
calibração e histórico de retreinamento dos três modelos do projeto (times,
jogadores e zonas de arremesso), independente de qual time/jogador/
adversário está selecionado nas páginas de análise. Duas abas:

- **Métricas atuais**: o retreinamento mais recente de cada modelo
  (accuracy/Log Loss/Brier/MAE para times; MAE e cobertura de intervalo
  para jogadores; MAE de pontos de bola-de-quadra e MAE de participação
  por zona para o modelo de zonas);
- **Histórico de treinamento**: gráfico de evolução dessas métricas ao
  longo de cada `python scripts/retrain_models.py` já rodado.

Atualize rodando o comando acima no terminal.

## Dados e Atualizações

Acesse pela barra lateral do Streamlit ("Dados e Atualizações") — separa a
tarefa de importar dados da tarefa de explorar resultados (seção 3 do
planejamento de UI/UX), trazendo parte da coleta para dentro da interface:

- **Jogos e jogadores por temporada**: baixa uma temporada inteira (jogos +
  boxscore de jogadores, poucas chamadas) direto pela tela, com barra de
  progresso;
- **Arremessos (incremental)**: coleta um lote pequeno (até 30 jogadores)
  de arremessos, também com progresso na tela.

Coletas grandes (muitas temporadas, ou centenas de jogadores de uma vez)
continuam melhor pelo terminal em segundo plano — a própria página avisa
isso e mostra o comando equivalente. Rating oficial e titularidade real
(uma chamada por jogo cada, ainda mais lentas) continuam só pelo terminal
(`scripts/update_advanced_stats.py`, `scripts/update_starter_status.py`).

## Próximas versões

- [x] Conector com `nba_api`;
- [x] Banco SQLite e atualização incremental;
- [x] Offensive/Defensive Rating oficiais (coleta incremental via `BoxScoreAdvancedV3`, com aproximação por pontos como reserva enquanto a coleta não cobre todos os jogos);
- [x] Estatísticas reais dos 30 times na base demonstrativa (offense/defense calibrados pela média real de pontos da temporada 2024-25; pace estimado, sem Rating oficial pace-ajustado para os 30 ainda; os jogos em si continuam simulados);
- [x] Módulo de jogadores (primeira versão: game logs, eficiência, per-36, consistência, comparador);
- [x] Índice próprio (NAPS) e estilo de jogo (primeira versão: sem segmentação por posição, sem impacto on/off, defesa por proxy simples);
- [x] Previsão de minutos, pontos, rebotes e assistências (primeira versão: sem dados de lesões/escalação do adversário);
- [x] Simulação de classificação, Play-In e playoffs (primeira versão: força congelada no corte, sem critérios oficiais de desempate);
- [x] Registro permanente das previsões (times e jogadores, registro manual por botão, resolução sob demanda contra jogos reais já coletados — previsões novas são resolvidas pela data-alvo e conferem adversário/mando quando disponíveis; registros legados sem esses campos usam fallback compatível);
- [x] Retreinamento automático (script `scripts/retrain_models.py` + histórico de métricas; agendamento da execução periódica fica a cargo do usuário);
- [x] Trajetória do jogador (segunda versão): passagem por time (`team_stint`), contexto do adversário (força defensiva), médias móveis exponenciais, decomposição de pontos em volume × eficiência e validação walk-forward para o log de métricas do modelo de jogadores;
- [x] Probabilidade por faixa e Usage Rate por passagem no modelo de pontos;
- [x] Filtros de período/casa-fora/adversário/minutos e marcador de troca de time na página de jogadores;
- [x] Coleta de titularidade (titular/reserva) via `BoxScoreTraditionalV3`, incremental e lenta como o Rating oficial, com aproximação por minutos acima da mediana do time enquanto não coletada;
- [x] Intervalos por regressão quantílica (opcional, `interval_method="quantile"`): alternativa ao intervalo Normal, comparável via cobertura no `walk_forward_evaluate`; `"normal"` continua sendo o padrão do app.
- [x] Mapa de arremessos (coleta via `ShotChartDetail`, análise por zona com suavização bayesiana, mapas de pontos/calor/hexagonal, comparações com explicação automática, modelo de previsão de distribuição/eficiência por zona validado por walk-forward);
- [x] Interface reorganizada (Visão Geral, Times, Qualidade do Modelo e Dados e Atualizações como páginas próprias; sistema de design compartilhado em `src/ui/`: selos de fonte/atualização, estados padronizados, seletores com preferência salva na URL, explicações automáticas em linguagem natural);
- [x] Coleta de dados reais direto pela interface (jogos/jogadores por temporada e lotes pequenos de arremessos), sem precisar do terminal para o dia a dia;
- [ ] Layout responsivo para telas menores — não verificado ainda (sem acesso a navegador nas sessões em que foi construído);
- [ ] Rating oficial e titularidade real ainda cobrem uma fração pequena da base coletada (a app usa a aproximação por pontos/minutos na maioria dos jogos).



## Auditoria das previsões de jogadores (2026)

A projeção de minutos agora combina a saída do modelo com médias de rotação
recente e temporada anterior, ponderadas pela quantidade de jogos no stint atual.
A confiança considera resíduos históricos de minutos, pontos, rebotes e
assistências e o tamanho do histórico; ela é uma classe heurística de incerteza,
não uma probabilidade de acerto.

Para gerar um backtest progressivo por data e salvar previsões individuais, no
Windows dê dois cliques em `RETREINAR_MODELOS.bat`. Ou, com o ambiente virtual
ativado no PowerShell, execute:

```powershell
python scripts/retrain_models.py
```

O relatório `reports/player_backtest_predictions.csv` inclui data, fold, jogador,
time, adversário, previsão, resultado e erro de minutos/PTS/REB/AST. A página
**Qualidade do Modelo** exibe MAE por rodada e por jogador e permite exportar o CSV.

Ao registrar uma previsão na página **Jogadores**, selecione a data exata da
partida. A resolução na página **Desempenho** usa essa data e confere adversário
e mando quando os dados permitem, evitando associar a previsão à partida errada.
As previsões antigas são migradas automaticamente; quando não têm data-alvo, a
resolução tenta verificar adversário/mando. Confira também
`docs/AUDITORIA_PREVISOES_JOGADORES.md`.


## Próximo confronto do jogador

Na página **Jogadores → Projeções**, quando a fonte de dados real está selecionada, o app consulta o calendário público oficial da NBA e procura o próximo jogo agendado para a equipe escolhida. Se o calendário estiver indisponível, o confronto pode ser preenchido manualmente. Veja [a documentação](docs/PROXIMO_JOGO_JOGADOR.md).

## Correções de compatibilidade e contexto defensivo — 21/10/2026

A tela **Qualidade do Modelo** agora continua a funcionar com logs de treinamento antigos que ainda não têm as métricas comparativas da temporada-base. A previsão de pontos também aplica um ajuste pequeno e limitado para considerar o defensive rating do adversário; consulte [`docs/CORRECAO_FALHAS_TESTES_2026-10-21.md`](docs/CORRECAO_FALHAS_TESTES_2026-10-21.md) para detalhes e limitações.
