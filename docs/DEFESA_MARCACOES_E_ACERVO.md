# Defesa, marcações e acervo desde 2022

O sistema conserva os arquivos públicos originais e suas versões em
`data/history/`. O catálogo `nba_history.sqlite` registra URL, data de publicação,
data de coleta, SHA-256, tamanho, linhas e colunas de cada arquivo. O ano dos
arquivos é o **ano final** da temporada: 2022 corresponde a 2021–22. Essa temporada
é incluída para cobrir também os jogos do calendário de 2022.

A carga de referência da versão 1.1.0 contém 826 arquivos, com aproximadamente 15,47 milhões de linhas
entre conjuntos sobrepostos: NBA/ESPN boxscores, eventos, arremessos, posses,
escalações, métricas avançadas, tracking, hustle, matchups e play types. Esses
registros não representam jogos únicos. A tela **Defesa dos times → Fontes e
cobertura** permite inspecionar os conjuntos e exportar seu catálogo.

Pré-temporada, temporada regular, play-in, playoffs e finais de NBA Cup permanecem
identificados. O histórico ampliado fica separado das tabelas de treinamento
regular e das previsões pessoais. Escalações inferidas por quarto, presentes em
alguns arquivos, não são stints validados para RAPM.

## Defesa dos times

| Indicador | Origem e cálculo |
|---|---|
| DRtg | NBA Stats quando a amostra corresponde à fase inteira; em janelas recentes, pontos adversários por 100 posses estimadas |
| Posses estimadas | Média dos dois lados de `FGA + 0,44 × FTA − OREB + TOV` |
| PITP cedidos/jogo | `opp_pts_paint` NBA Stats; alternativa: pontos no garrafão dos adversários nos boxscores ESPN |
| 3PA cedidas/jogo | Soma das tentativas de três adversárias / jogos completos |
| 3P% cedido | Soma dos acertos de três / soma das tentativas; não é média simples de percentuais |
| FG% cedido a <6 pés | Acertos/tentativas por coordenadas dos eventos NBA |
| DFG% <6 pés | Somente o dashboard oficial de tracking `LeagueDashPtTeamDefend`, quando acessível |

As regiões por coordenadas são classificações geométricas documentadas, sem
identificar o defensor mais próximo. O aro usa distância radial menor que seis
pés; o restante do garrafão usa a faixa de 16 pés de largura, da linha de fundo à
linha de lance livre. Corner 3 usa `|x|≥22` pés e `y≤14` pés. Os jogos só entram no
detalhamento regional quando todas as FGA adversárias são conferidas contra o
boxscore. Tentativas sem coordenadas não viram arremessos no aro.

O tracking individual **Quem protege o aro** utiliza `def_rim_fgm/def_rim_fga`,
com definição própria do NBA Player Tracking. Não somamos defensores para criar
um DFG% de equipe. Ausência de tracking aparece como dado indisponível.

Todas as taxas incluem os minutos registrados, inclusive garbage time. Não há
filtro equivalente ao Cleaning The Glass. Os rankings iniciais são provisórios;
a amostra e a data aparecem na tela.

## Quem marcou quem

**Marcações e encaixes** consulta a tabela normalizada de `BoxScoreMatchupsV3`:

- atacante, defensor, equipe e partida;
- segundos atribuídos e posses parciais, mantendo suas casas decimais;
- pontos, FGM/FGA, 3PM/3PA, assistências e turnovers atribuídos;
- trocas defensivas e faltas registradas;
- posição do defensor, quando identificada no elenco daquela temporada.

Uma partida tem vários defensores por atacante. A coluna de maior tempo atribuído
não significa marcação exclusiva. Esses dados são agregados por jogo e par de
jogadores: não formam uma sequência de atribuições segundo a segundo, nem uma
reconstituição da ajuda defensiva por câmera.

Os arquivos disponíveis cobrem temporadas anteriores. Nesta coleta, o arquivo
por partida de 2026–27 ainda estava ausente e a consulta direta a stats.nba.com
foi recusada pela conexão. A cobertura efetiva aparece por temporada/fase. O
coletor tenta retomar os jogos atuais e interrompe um lote na primeira recusa da
fonte, sem fabricar defensores com base em posição ou escalação.

## Encaixe do jogador contra perfis defensivos

Os perfis do adversário são calculados **antes da data de cada partida**, usando
os últimos dez jogos da equipe, com mínimo de cinco. A classificação por terços
da liga considera:

- garrafão: PITP cedidos por 100 posses estimadas;
- perímetro: média dos percentis de 3PA cedidas por 100 posses e 3P% cedido;
- eficiência geral: DRtg estimado.

A produção do jogador é apresentada em PTS/jogo e PTS/36 minutos. Cada perfil é
comparado com os demais perfis do mesmo jogador, temporada e fase. Um bootstrap
determinístico de 1.000 reamostragens estima o intervalo de 95% da diferença de
PTS/36. A interpretação exige dez jogos e 200 minutos em cada grupo; intervalos
que incluem zero permanecem incertos. Jogos com menos de dez minutos são
excluídos dessa comparação de taxas.

São associações exploratórias, sem ajuste causal completo para escalações,
lesões, função ofensiva e força do calendário. Os perfis descrevem concessão
estatística, não identificam esquemas táticos como zona, drop ou blitz. Uma
hipótese sobre Jalen Brunson, por exemplo, só aparece como produção maior
observada se houver suporte na amostra. Esta análise não modifica automaticamente
os modelos de player props; adicionar interações exige nova validação temporal.

## Coletar e atualizar

No sistema, use **Dados e atualizações → Base ampliada desde 2022**. A coleta usa
até quatro downloads simultâneos, valida o Parquet antes de substituir uma versão
e confere o SHA-256 dos arquivos já disponíveis. É retomável por arquivo.

No ambiente de desenvolvimento:

```powershell
python scripts/collect_history.py --start-year 2022
python scripts/collect_history.py --start-year 2027 --end-year 2027 --core
```

Enquanto o sistema está aberto, uma tarefa independente atualiza os conjuntos
defensivos da temporada atual a cada seis horas, sem prender a consulta dos
placares ao vivo. Ela também tenta recuperar matchups atuais pendentes. O pacote
Windows inclui o acervo público presente na compilação, sem chaves, caches de APIs
autenticadas ou análises pessoais.

Fontes: [SportsDataverse NBA](https://github.com/sportsdataverse/sportsdataverse-data/releases),
[tracking defensivo de times](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguedashptteamdefend.md),
[BoxScoreMatchupsV3](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/boxscorematchupsv3.md).
