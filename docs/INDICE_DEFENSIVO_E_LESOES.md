# Índice defensivo, mapas e disponibilidade

Na versão 1.2.0, **Defesa dos times → Índice e gráficos** acrescenta um parâmetro
descritivo de 0 a 100. Maior significa melhores percentis entre equipes elegíveis
na mesma temporada, fase e janela de jogos.

Os pesos iniciais são 40% para DRtg, 20% para PITP cedidos por 100 posses
estimadas, 20% para aproveitamento de três cedido e 20% para percentual de
rebotes defensivos. Pesos e amostra mínima podem ser alterados. Os pesos
positivos são normalizados; empates recebem percentil médio. Equipes sem algum
critério ativo ficam sem nota. O garrafão exige cobertura em todos os jogos da
amostra. Com menos de duas equipes elegíveis, não se calcula o índice.

Essa combinação é exploratória, sem calibração preditiva ou equivalência a uma
probabilidade. Há sobreposição entre critérios, como DRtg e conversão adversária.

## Mapas e gráficos

**Por time** mostra arremessos adversários localizados pelo PBP NBA, em células
de três pés, coloridas por FG% cedido ou volume. O filtro de tentativas mínimas
oculta células com pouca exposição. Coordenadas ausentes ou fora da meia quadra
não são colocadas artificialmente no aro. Só entram jogos com todas as FGA
adversárias conferidas contra o boxscore.

O mapa representa localização dos arremessos, sem inferir posicionamento dos
defensores, esquema tático ou qualidade esperada do chute. Arremessos além da
meia quadra ficam fora da área desenhada. A legenda informa a amostra antes
desse corte espacial e do filtro por célula.

Há comparação de conversão por região com a liga, ponderada pelas tentativas,
e evolução do DRtg estimado pela soma dos pontos e posses dos últimos dez jogos,
com mínimo de cinco. A evolução percorre toda a fase escolhida. A cobertura de
mapas e regiões pode ser menor que a amostra geral quando faltam coordenadas.

## Produção contra o marcador

**Marcações e encaixes → Analisar → Marcador** exibe os atacantes enfrentados por
um defensor e seus pontos, posses parciais, FGA, FG%, 3P% e eFG%. O eFG% usa
`(FGM + 0,5 × 3PM) / FGA`.

A referência de cada atacante é seu FG% contra os outros defensores na mesma
temporada e fase. A comparação exige cinco FGA no confronto e vinte FGA na
referência. A diferença geral pondera as referências pelo volume de cada atacante
contra o defensor selecionado, usando os mesmos atacantes nos dois lados.
Ausência de amostra produz um traço, não zero.

Essa diferença não isola causalmente a habilidade do marcador: seleção dos
confrontos, trocas, ajuda, local dos chutes e companheiros influenciam a produção.
Posses parciais não são denominador de DRtg individual. A cobertura continua
explícita; marcações indisponíveis não são inventadas a partir de escalações.
Atletas transferidos podem ter registros em várias equipes na mesma fase.

## Lesões e disponibilidade

### Conexões em outra rede ou computador

As recusas observadas nesta rede não desativam NBA, ESPN ou endpoints de tracking.
A versão 1.2.0 mantém as consultas diretas e as alternativas. Em outro computador,
o sistema usa o perfil local daquele usuário e tenta as mesmas fontes, sem exigir
alteração do código por causa das falhas observadas aqui.

Os intervalos entre tentativas são temporários: placares NBA/ESPN voltam a ser
consultados após cinco minutos de espera por falha; lesões tentam primeiro a ESPN
a cada ciclo de cinco minutos. Quando a fonte direta responde novamente, seus
dados recentes substituem a alternativa mais antiga. Matchups pendentes voltam
a ser tentados nos lotes seguintes da atualização do acervo, a cada seis horas,
e podem ser consultados manualmente na tela da partida. Tracking direto também
continua disponível pelos botões de consulta.

As frequências de atualização, os limites de chamadas e os avisos de dados
defasados permanecem ativos. O sistema precisa estar aberto e conectado para
realizar consultas automáticas. Uma recusa de conexão descreve aquela tentativa;
não determina que o serviço será inacessível em todas as redes.

### Fontes e atualização do boletim

**Lesões e disponibilidade** mantém jogador, equipe, situação, motivo informado,
data da informação, retorno estimado e nota original da fonte. O monitor consulta
a cada cinco minutos enquanto o sistema está aberto; a tela relê o boletim a cada
minuto. A consulta manual respeita trinta segundos entre tentativas por base.

A consulta direta usa o endpoint público ESPN `/nba/injuries`. Na falha, consulta
o arquivo público `espn_nba_injuries` do SportsDataverse. O arquivo reúne várias
datas: só o último snapshot completo é usado, evitando manter alguém lesionado
porque constava em boletins antigos.

A alternativa é diária e seu intervalo de publicação pode ser maior que o do
monitor. A interface separa referência do boletim, fonte e hora da tentativa. A
consulta direta é marcada como defasada após quinze minutos; o arquivo diário,
após seis horas da publicação. Uma alternativa mais antiga não substitui uma
consulta direta recente. Falhas ou mudanças de formato preservam o último
boletim válido. Só um boletim explicitamente válido e vazio limpa a lista anterior.

Na verificação de 29/10/2026, a ESPN recusou a conexão nesta rede. A alternativa
tinha referência de 28/10/2026 e 93 registros, identificados como defasados.
Esses números registram a validação; não são contagem fixa da aplicação.

Em **Jogos do dia**, os destaques de hoje e datas futuras recebem o status atual,
com aviso de defasagem. Não se aplica o boletim atual a jogos históricos. O
cruzamento usa nome normalizado e equipe; IDs ESPN permanecem separados dos NBA.
Ausência na lista não confirma participação. Retornos são estimativas da fonte.
Os modelos não recebem ajustes automáticos de probabilidade a partir do boletim.

### Elegibilidade em Palpites de hoje — versão 1.2.1

Jogadores presentes no boletim com lesão, suspensão ou dúvida de participação são
retirados antes do ranking dos destaques. A regra é conservadora: inclui dia a
dia, questionável, improvável, provável e status não classificado. Um registro
explicitamente disponível pode voltar à seleção. Não se altera o valor das
projeções dos demais jogadores.

O cruzamento usa o nome completo normalizado, sem busca parcial e sem confundir
IDs ESPN com NBA. A exclusão também cobre transferências ainda não refletidas
na equipe histórica. Um nome completo idêntico é excluído conservadoramente.

Os próximos atletas elegíveis ocupam as vagas no ranking. O boletim é lido fora
dos caches de modelos e conferido novamente durante a geração. A página verifica
mudanças a cada trinta segundos para atualizar a seleção. Sem nenhum boletim
válido recebido, os palpites individuais ficam suspensos; os palpites dos times
continuam acessíveis. Um boletim defasado mantém os impedimentos conhecidos,
com o aviso de referência antiga. Ausência na lista não confirma escalação.

A prévia de previsões salvas dentro de Palpites de hoje aplica o mesmo filtro.
O histórico original continua imutável e permanece completo na tela Histórico
diário. Novos registros pré-jogo excluem as lesões conhecidas antes de selecionar
os destaques, preservando o histórico usado no treinamento.

Fontes: [boletim oficial NBA](https://official.nba.com/nba-injury-report-2026-27-season/),
[ESPN](https://www.espn.com/nba/injuries),
[acervo de lesões](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/espn_nba_injuries).
