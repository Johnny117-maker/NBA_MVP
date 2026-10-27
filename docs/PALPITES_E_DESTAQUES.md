# Jogos do Dia e Palpites de Hoje

## Análise e melhorias aplicadas

Os atletas ficavam dentro de tabelas recolhidas por confronto. A abertura de Jogos
do Dia agora prioriza os jogadores, com cartões de pontos, rebotes, assistências,
minutos, sequência de pontuação, diferença contra a temporada e último jogo.
Filtros por time, nome literal, perfil e produção permitem encontrar um atleta.
O link de cada cartão abre o perfil correto pelo ID, inclusive após troca de time.
Confrontos e Central da partida continuam em abas próprias. As preferências e a
fonte do calendário ficam no botão Ajustes, preservando espaço para os cartões.

A média recente antes podia misturar temporadas na virada do calendário. Agora
usa até cinco partidas da temporada mais recente de cada jogador e informa o
tamanho real da amostra. O selo Em alta compara com a média dessa temporada.
Impacto = pontos + 0,7 × rebotes + assistências. Mantêm-se os critérios de dez
minutos em média e atuação a até 45 dias da partida mais recente da base.
Essa elegibilidade relativa à base não comprova participação no jogo de hoje.

Uma modificação recente no arquivo SQLite não comprova que as partidas também
sejam recentes. O aviso usa a data real da última partida dos jogadores. Em
27/10/2026, a base de desenvolvimento contém histórico até 12/04/2026; os cartões
são identificados como referências históricas, com participação não confirmada.

## Nova tela Palpites de Hoje

Disponível no menu Explorar, na página inicial e por um atalho em Jogos do Dia.
O dia segue o fuso da costa leste dos EUA, como o calendário da NBA.

- Entram apenas partidas agendadas para hoje. Status em andamento, encerrado e
  adiado/cancelado são excluídos. Um horário UTC já passado também exclui o jogo,
  mesmo se o arquivo periódico ainda indicar agendado.
- Horário desconhecido permanece com identificação Horário a confirmar.
- Calendário salvo e confrontos manuais da sessão continuam disponíveis quando
  a consulta falha. As origens aparecem nos critérios da seleção.
- A aba de jogadores começa com as médias recentes e um botão explícito para
  gerar projeções. É possível escolher de um a três destaques por equipe.
- O modelo individual fornece pontos, rebotes, assistências, minutos estimados e
  faixas experimentais. Exige ao menos três partidas recentes para projetar o atleta.
- A aba de confrontos mostra a preferência do modelo, chance estimada, placar,
  faixas e os dois fatores de maior magnitude. O CSV inclui a data, origem e
  limite do histórico para revisão posterior.
- Histórico com mais de 14 dias reduz a classe exibida para Baixa · histórico
  antigo. A probabilidade bruta do modelo continua identificada como estimativa;
  a classe de confiança não representa uma taxa de acerto.

Os palpites são cenários caso os atletas participem. A base não confirma lesões,
minutagem atual ou escalações. As faixas individuais são experimentais.

## Compartilhamento e atualização

`src/round_context.py` reúne calendário, histórico anterior ao dia selecionado,
forma e modelos usados nas duas páginas. O calendário e os modelos são reutilizados
entre telas; o botão Atualizar calendário altera a chave compartilhada. Falhas de
rede não são guardadas durante uma hora. A versão do banco e o dia entram nas
chaves do histórico e das projeções. Os placares do próprio dia são excluídos.

O treino individual usa no máximo 40 mil linhas recentes de jogadores, mantendo
datas inteiras para não cortar boxscores. Esse limite reduz a memória exigida;
o recorte e suas datas aparecem nos detalhes de cada projeção. Os snapshots usam
a carreira completa do atleta e os boxscores completos dos jogos dele, preservando
a mediana de minutos por equipe sem copiar o histórico inteiro da liga. Essa janela
de treino não promete a mesma precisão de um treino com toda a base histórica.
Uma falha de memória interrompe a geração com mensagem na interface e permite
voltar às médias dos destaques na próxima execução.

## Próximas prioridades da análise

1. Atualizar a coleta de jogos/boxscores recentes e verificar cobertura por equipe.
2. Integrar uma fonte de elenco e disponibilidade de atletas que responda nesta rede.
3. Acompanhar erro e cobertura das projeções resolvidas antes de destacar confiança alta.

## Verificação

A suíte completa passou com 274 testes. Foram adicionadas verificações de virada
de temporada, amostra efetiva, seleção de jogos futuros, horário de início,
confiança em histórico antigo, ausência de treino automático de jogadores,
geração explícita, busca literal, reutilização do calendário e navegação para o atleta pelo ID.
Os testes também verificam o limite do treino, a preservação dos snapshots e a
recuperação da interface após falta de memória. Ruff e mypy
validam 50 arquivos de produção. A conferência no navegador gerou as projeções
dos oito destaques com a base real: 39.992 linhas de treino entre 17/01/2025 e
12/04/2026, sem repetir a falha de memória do treino com 202.840 linhas.
