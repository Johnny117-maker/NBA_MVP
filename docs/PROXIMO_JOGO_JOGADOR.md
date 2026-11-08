# Previsão do próximo confronto do jogador

## O que mudou

Na aba **Jogadores → Projeções**, para a fonte **Dados reais (coletados)**, o sistema consulta o calendário público da NBA e localiza o próximo jogo programado da equipe selecionada. Quando encontrado, o formulário sugere:

- adversário oficial e mando de quadra;
- data do confronto e, quando disponibilizado pelo feed, horário de início em Eastern Time;
- dias de descanso estimados a partir do último jogo que existe no histórico local;
- rating defensivo do adversário, somente se a base local contiver jogos desse time.

A agenda é mantida em cache por uma hora para reduzir chamadas de rede. O módulo tenta duas variantes do arquivo JSON público do calendário. Se a consulta falhar, a tela avisa e permite preencher o cenário manualmente.

## Limitações importantes

1. A equipe identificada pelo histórico mais recente é apenas uma sugestão. Se o jogador mudou de time na offseason e ainda não jogou pela nova equipe no banco local, selecione a equipe atual no campo **Equipe atual para localizar o próximo jogo**.
2. O calendário da NBA informa jogos das equipes, não confirma que um jogador específico estará disponível, será titular ou terá minutos normais. Lesões, descanso e restrições de minutos precisam de dados pré-jogo adicionais.
3. O banco local pode não ter ratings defensivos atualizados para a equipe adversária. Nessa situação, o modelo usa a média de defesa da liga e informa essa limitação.
4. A base demonstrativa é sintética e não representa jogadores reais; por isso, a detecção automática do calendário fica disponível apenas com dados reais.
5. Se o usuário alterar a data sugerida, a previsão passa a representar a data manualmente escolhida. Ao registrar, a resolução posterior continua exigindo correspondência de data, adversário e mando quando esses dados existem.

## Fonte do calendário

O módulo `src/nba_schedule.py` tenta o JSON público utilizado pelo calendário da NBA:

- `https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json`
- fallback: `https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json`

O parser está isolado da requisição HTTP para ser testado com fixtures sem acesso à internet: `tests/test_nba_schedule.py`.

## Validação

Execute `windows/EXECUTAR_TESTES.bat` no Windows para rodar toda a suíte. Os testes de calendário verificam a leitura de partidas, escolha do próximo jogo futuro, exclusão de partidas finalizadas/que já começaram e retorno vazio quando não há confronto futuro. A consulta ao CDN depende de conectividade externa e não pode ser validada em ambiente offline.

## Resiliência do calendário

A aplicação tenta primeiro os dois JSONs públicos de calendário da NBA. Se ambos falharem (por exemplo, quando uma rede encerra a conexão com `cdn.nba.com`), tenta o placar público da ESPN, consultando as datas futuras individualmente. Os jogos indicam a fonte (`NBA oficial` ou `ESPN (alternativo)`) na interface.

Se as duas fontes estiverem bloqueadas ou indisponíveis, a tela deixa de exibir a lista bruta de erros de conexão. Ela informa que a consulta automática falhou e mantém os campos manuais para adversário e data. O calendário ESPN é uma alternativa pública, não uma garantia: conexões corporativas, proxies e firewalls também podem bloqueá-lo.
