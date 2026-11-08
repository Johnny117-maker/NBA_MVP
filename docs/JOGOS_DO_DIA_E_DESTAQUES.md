# Jogos do Dia e jogadores em destaque

A página `pages/7_Jogos.py` lista os confrontos do calendário NBA selecionado, exibe horários em Brasília e ET, status e arena quando disponíveis. A camada `src/daily_games.py` calcula a forma dos jogadores com médias dos últimos cinco jogos, compara a pontuação recente com a média da temporada mais recente e identifica perfis como cestinha, reboteiro, criador e atleta em alta.

As duas entradas anteriores do Git, que diferiam apenas na capitalização de
`Dia`/`dia`, foram consolidadas nesse caminho único para compatibilidade entre
Windows e Linux. O atalho da página inicial e os testes usam o mesmo arquivo.

## Probabilidade experimental de vitória

Quando há dados reais suficientes, a página usa `train_models` e `predict_game`,
os mesmos da página Times. A fórmula aproximada paralela foi removida. A coleta
de estatísticas de jogadores não é necessária para calcular a probabilidade dos
times. Sem histórico suficiente para treinar (mínimo de 50 partidas), o calendário
continua disponível e a interface explica a ausência das probabilidades.

O carregamento dos dados e o treinamento são reutilizados entre os confrontos,
com cache invalidado pela atualização do banco ou mudança da data selecionada.
Os registros de times e jogadores são filtrados para datas estritamente anteriores
à selecionada. O elenco atual é consultado apenas para hoje e datas futuras;
consultas a dias passados usam os times históricos.

O descanso segue a convenção do treinamento: diferença entre as datas das partidas
(jogos em dias consecutivos = 1), limitada a 7 dias. Na página Times, esse valor é
informado manualmente, portanto as probabilidades só devem coincidir quando o
histórico, o mando e o descanso forem iguais. A estimativa continua experimental;
usar o mesmo modelo não demonstra ganho de precisão.

## Limitações importantes

- Para mostrar destaques reais, execute a coleta em **Dados e Atualizações**; a página não inventa nomes nem usa atletas sintéticos como se fossem reais.
- O banco pode estar desatualizado durante a offseason; confira a data de atualização.
- A base atual não confirma lesões, titulares ou restrições de minutos. O destaque estatístico pode não jogar.
- O calendário tenta NBA oficial, arquivo público SportsDataverse/GitHub e ESPN,
  nessa ordem, conforme `src/nba_schedule.py`.

## Fonte gratuita alternativa sem chave de API

Quando a rede não alcança os serviços NBA, a aplicação baixa o CSV público do
[SportsDataverse / hoopR](https://github.com/sportsdataverse/hoopR-nba-data),
distribuído nos
[arquivos públicos de calendário ESPN](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/espn_nba_schedules).
Não requer cadastro, chave, pacote adicional nem acesso direto ao domínio ESPN.

O arquivo é identificado pelo ano final da temporada: `nba_schedule_2027.csv`
corresponde a 2026–27. O adaptador `src/public_schedule.py` normaliza códigos de
equipe, datas em ET, horários UTC e status; equipes indefinidas são omitidas,
horários não confirmados continuam indefinidos e partidas adiadas/canceladas não
são selecionadas como próximo jogo. O cache reúne provedores sem duplicar o mesmo
confronto quando seus identificadores diferem.

A interface identifica a origem e informa que é um arquivo com atualização
periódica, sem garantia de placares ou status em tempo real. Nesse modo, usa os
times registrados no histórico dos jogadores, evitando nova espera no endpoint de
elenco NBA bloqueado. O calendário não atualiza as estatísticas individuais do
banco local.

Dados sob [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), com atribuição
ao SportsDataverse/hoopR na interface. A transformação feita pela aplicação é a
normalização de campos e filtragem de registros inválidos.

Teste real em 27/10/2026: o arquivo foi baixado nesta máquina, 1.200 confrontos
com equipes identificadas foram normalizados e quatro jogos foram encontrados
para a data. A cópia local foi salva. Validação automatizada: 51 testes passaram
nos módulos afetados; Ruff passou e mypy validou os 44 arquivos de produção.

## Quando NBA e ESPN não respondem

Se aparecer `fetch_nba_schedule() got an unexpected keyword argument 'start_date'`
após uma atualização, o processo do Streamlit pode estar com a versão anterior
do módulo em memória. Encerre o servidor com `Ctrl+C`, execute novamente
`windows/INICIAR_PROJETO.bat` e atualize a página no navegador. Apenas recarregar a página
não garante o recarregamento dos módulos Python do servidor.

A página salva os calendários recebidos em `data/nba_schedule.json`, fora do Git.
Se as três fontes falharem, tenta usar essa cópia local e sinaliza que horários e
status podem estar desatualizados. A cópia só passa a existir depois de uma
consulta bem-sucedida; o sistema não gera confrontos automaticamente sem fonte.
As falhas de rede não ficam retidas no cache de uma hora. O botão **Atualizar
calendário** continua forçando uma nova consulta.

Se ainda não houver uma cópia válida para a data selecionada, use **Informar
confronto manualmente**: escolha mandante, visitante e horário em ET e clique em
**Analisar confronto**. O confronto fica identificado como **Cadastro manual** e
permanece somente na sessão atual. Destaques e probabilidades continuam dependendo
do histórico coletado no banco. Quando o calendário falha, a consulta ao elenco
atual é dispensada para evitar outra espera de rede; são usados os times históricos.

O fallback da ESPN recebe a data selecionada, inclusive para dias passados.
Essas alternativas mantêm a análise utilizável durante a falha; não restabelecem
a conexão com os serviços externos nem fornecem resultados ao vivo.

Validação da recuperação de rede: 26 testes passaram nos módulos de calendário,
armazenamento local, página Jogos e página inicial. Os testes cobrem uso da cópia
salva, falha ao gravar o cache, cadastro manual e sua manutenção entre interações,
rejeição de times iguais e novas tentativas após falhas. Ruff passou nos arquivos
alterados dessa correção; mypy passou nos 43 arquivos de produção.

## Validação realizada

- Compilação sintática de `app.py`, páginas, `src` e testes (`compileall`).
- Testes manuais de fumaça para médias recentes, ranking, filtro de jogadores inativos, aliases de times, conversão de horário e rótulos de status.
- Regressões automatizadas em `tests/test_daily_games.py` e
  `tests/test_daily_games_page.py` cobrem descanso, probabilidade sem dados de
  jogadores, exclusão de partidas na data-alvo e datas futuras, falha da consulta
  de elenco e manutenção do calendário quando faltam jogos para treinar.
- Os testes da página substituem as consultas externas por respostas locais.

### Verificação de 27/10/2026

- Suíte completa: 212 testes passaram.
- Após adicionar mais três regressões (destaques sem resultados do dia-alvo,
  consulta histórica sem elenco atual e ativação das projeções individuais),
  os três arquivos de testes afetados foram executados novamente: 25 passaram.
- Ruff passou nos arquivos Python alterados; mypy passou nos 42 arquivos de
  produção (`src`, `pages`, `app.py` e `scripts`).
- A execução usou banco sintético de testes e respostas externas substituídas;
  não atualizou o banco real nem mediu ganho de precisão dos modelos.
