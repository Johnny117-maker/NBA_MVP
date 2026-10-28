# Temporada atual, forma recente e Over/Under — 28/10/2026

Ao abrir o projeto pelo `INICIAR_PROJETO.bat`, a primeira página inicia um monitor
compartilhado. Ele continua trabalhando enquanto o servidor estiver aberto,
mesmo quando outra aba do projeto estiver selecionada ou o navegador estiver
em segundo plano. Fechar o servidor, suspender ou desligar o computador interrompe
a coleta. Não foi instalado um serviço do Windows nem uma tarefa do Codex.

## O que aparece no aplicativo

- A Visão Geral começa pelas oportunidades da rodada de pontos, rebotes e assistências.
- A nova página **Over / Under ao vivo** reúne oportunidades, placares e estatísticas,
  análise de uma linha específica e o estado das fontes.
- A análise individual compara Over, Under e devolução em linhas inteiras.
- Jogos do Dia e Palpites reutilizam o calendário sincronizado quando ele existe.
- Dados e Atualizações mostra o estado da coleta automática.

Sem uma chave de odds, as linhas são **referências estatísticas**, não linhas de
casas. A referência parte da média da temporada e recebe apoio do histórico
anterior quando há menos de cinco jogos atuais. Isso evita destacar como
“oportunidade” a diferença artificial causada por uma primeira partida atípica.
A seleção automática exige três jogos na temporada atual, contexto recente e
projeção de pelo menos 15 minutos. A análise individual aceita amostras menores,
explicitamente identificadas.

As probabilidades são estimativas experimentais. Não representam uma estratégia
com lucro demonstrado nem foram calibradas em um backtest de snapshots ao vivo.
As referências estatísticas permitem explorar a forma; para comparar uma oferta
real, informe a linha desejada ou consulte a The Odds API com uma chave própria.

## Fontes e frequência

| Fonte | Padrão | Recursos usados | Limites deste projeto |
| --- | --- | --- | --- |
| NBA CDN pública | Ativa | Scoreboard e boxscore do jogo | 30 s durante jogos ativos; frequência reduzida fora da rodada |
| ESPN pública | Ativa | Scoreboard por data e summary/boxscore | Mesmo monitor; 5 min de espera após falha |
| SportsDataverse/ESPN | Ativa | Calendário e boxscores individuais da temporada | Arquivos consultados a cada hora; não são um feed ao vivo |
| API-Sports/API-NBA ou RapidAPI | Opcional | Jogos e estatísticas individuais por jogo | Até 95 chamadas/dia; cache de 15 min |
| balldontlie | Opcional | Jogos; boxscores quando o plano permitir | Até 5 chamadas/minuto; plano grátis não consulta boxscores |
| The Odds API | Opcional | Linhas de PTS/REB/AST por evento | Consulta por botão, até 12 créditos/dia e 450/mês |

O monitor adapta o intervalo entre 30 segundos e cinco minutos; perto do início
de partidas usa um minuto. O painel visual consulta o estado local a cada 30
segundos. Todas as sessões compartilham a coleta; abrir várias abas não multiplica
as requisições. Uma trava no SQLite também evita dois processos coletando a mesma
base ao mesmo tempo. Após falhas de rede, a fonte aguarda cinco minutos.

Quando o histórico muda, as telas abertas são renovadas automaticamente e os
caches passam a usar a nova versão da base. As mudanças de placar/relógio no
banco de monitoramento não disparam essa renovação nem um treinamento completo.

O plano gratuito da [balldontlie](https://nba.balldontlie.io/#account-tiers) inclui
times, jogadores e jogos, mas não estatísticas de jogadores por partida nem
boxscores. A documentação lista boxscores para GOAT. Configurar uma chave grátis
não libera esses endpoints. A [API-NBA](https://www.api-football.com/news/post/how-to-get-started-with-api-nba-the-complete-beginners-guide)
informa 100 chamadas/dia no plano gratuito; isso não sustenta consultar todos os
boxscores a cada 30 segundos. Por isso o adaptador conserva a cota e não usa seu
cache de 15 minutos para condicionar uma análise como se fosse um boxscore atual.

A [The Odds API](https://the-odds-api.com/) anuncia 500 créditos/mês no plano
gratuito. O custo depende de mercados e regiões, conforme a
[documentação v4](https://the-odds-api.com/liveapi/guides/v4/#get-event-odds).
O projeto reserva créditos antes das consultas, inclusive se elas falharem,
com margem conservadora. Não há cadastro, assinatura ou contratação automática.

## Primeira coleta real

A sincronização inicial importou **56 partidas e 1270 registros individuais** de
2026–27, todos validados, com dados até **27/10/2026**. A base passou de 9509 para
9565 partidas e de 202840 para 204110 registros de jogadores. Antes dessa operação,
foi criada a cópia local `data/nba_before_auto_sync_2026-10-28.db`, ignorada pelo Git.

As conexões Python diretas à NBA e ESPN foram interrompidas pelo host remoto nesta
rede, inclusive fora do sandbox. Os arquivos públicos do SportsDataverse foram
acessíveis e forneceram os dados atuais. Essa alternativa resolve a atualização
periódica da temporada; não transforma arquivos históricos em acompanhamento ao
vivo. O painel identifica essa condição. Os adaptadores diretos serão utilizados
quando esses hosts estiverem acessíveis. A configuração padrão não exige chave.

## Integridade e identificação

O estado de monitoramento e o cache ficam em `data/nba_sync.sqlite`. O histórico de
treinamento continua em `data/nba.db`. Uma mudança de relógio não altera o histórico,
nem invalida ou retreina modelos. Somente um boxscore final validado entra nas
tabelas de jogos e estatísticas; as versões em memória são renovadas pela mudança
da base. O treinamento completo de jogadores/zonas não é disparado por tick.

Antes de inserir um resultado são conferidos o estado final, a temporada regular,
o placar, a presença de jogadores, minutos totais, pontos e rebotes. Ausência de
estatística não é convertida em zero. Boxscores rejeitados aguardam nova consulta.
Resultados repetidos usam um hash do conteúdo, preservando o arquivo de treinamento
quando nada mudou; correções da mesma fonte são atualizadas sem duplicação.

IDs ESPN, API-Sports e balldontlie não são convertidos diretamente em IDs NBA.
O cruzamento usa um identificador explícito compatível ou um nome completo único.
Jogadores ainda não conciliados recebem IDs locais negativos. Quando um ID NBA
oficial confirma a identidade, o histórico é conciliado. Partidas são conciliadas
por data, mando e equipes, com aliases também usados nos logs, ratings e arremessos.
As datas de partidas seguem o calendário NBA no fuso Eastern; os horários de
consulta apresentados no painel são convertidos para Brasília.

## Modelo durante a partida

O histórico usa somente datas anteriores ao confronto. A taxa por minuto combina
a temporada atual e as últimas cinco partidas, com um prior da temporada anterior
nas amostras curtas. Minutos previstos e dispersão vêm do histórico recente.
A distribuição preditiva de contagens é uma mistura Gamma–Poisson, implementada
como [binomial negativa no SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.nbinom.html).

Durante a partida, a taxa é atualizada com a produção observada e os minutos já
jogados. A exposição restante considera relógio, período, prorrogações e ocupação
da quadra nesta partida. Minutos futuros são estimados, não uma escalação
confirmada. Uma expulsão informada zera a exposição restante.

O boxscore precisa ter até 120 segundos de idade e relógio/minutos válidos.
Estatísticas ausentes, arquivos periódicos, dados antigos e linhas já decididas
não entram como novas oportunidades ao vivo. Não há previsão de lesões, substituições
futuras ou prorrogações que ainda não começaram.

## Uso e configuração

Para usar as fontes públicas, abra `INICIAR_PROJETO.bat`. Para um ciclo sem abrir
o aplicativo, use `ATUALIZAR_TEMPORADA.bat` ou, no ambiente virtual:

```powershell
python scripts/sync_current_season.py --once
python scripts/sync_current_season.py --watch
```

Para chaves opcionais, copie `.streamlit/secrets.example.toml` para
`.streamlit/secrets.toml`, preencha localmente e reinicie o servidor. O arquivo real
é ignorado pelo Git. Também são aceitas as variáveis `NBA_API_SPORTS_KEY`,
`NBA_RAPIDAPI_KEY`, `NBA_BALLDONTLIE_KEY`, `NBA_BDL_PLAN` e `NBA_ODDS_API_KEY`.
Não envie suas chaves no chat. Erros de requisição omitem URLs autenticadas.

`NBA_AUTO_SYNC=0` desativa o monitor automático. Os testes usam essa opção para
não depender de rede, horário ou APIs reais. Testes de coleta exercitam os serviços
diretamente com respostas controladas. Para verificar o atalho sem iniciar ou
encerrar processos, use `INICIAR_PROJETO.bat --verificar`.

Validação: 322 testes automatizados passaram; Ruff e mypy sem erros em 63 arquivos
de produção. Após a organização final dos filtros, os 13 testes de abertura,
navegação e da nova tela foram repetidos com sucesso. A interface foi conferida
no navegador com os dados reais de 2026–27 e a indisponibilidade do feed direto
identificada na tela.
