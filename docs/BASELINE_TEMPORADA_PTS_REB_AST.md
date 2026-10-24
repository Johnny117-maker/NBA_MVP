# Projeções ancoradas na temporada-base

## Objetivo

Usar as médias de pontos (PTS), rebotes (REB), assistências (AST) e minutos da temporada-base mais recente como ponto de partida e adaptar a estimativa à produção recente, minutos esperados, eficiência, adversário e troca de time.

## Engenharia das variáveis

`src/player_features.py::add_previous_season_baselines` cria as colunas `prev_season_pts_avg`, `prev_season_reb_avg`, `prev_season_ast_avg`, `prev_season_minutes_avg`, taxas por minuto e a quantidade de jogos que sustenta o baseline. Para rótulos NBA como `2025-26`, as médias vêm da temporada imediatamente anterior (`2024-25`) e agregam todos os times em que o atleta atuou naquele ano. Se esse ano não estiver no banco, usa-se apenas o histórico do jogador disponível antes da partida; em estreia absoluta, são usados priors neutros.

## Combinação da projeção

`src/player_model.py::_blend_season_baseline` combina a estimativa dinâmica com a taxa da temporada-base multiplicada pelos minutos previstos. O peso teórico da referência anual é `clip(0,60 - 0,04 × jogos_desde_troca, 0,20, 0,60)`, multiplicado por uma confiabilidade entre 0 e 1, baseada no tamanho da amostra (até 10 jogos). Assim, a referência tem maior influência imediatamente após a mudança de time e o padrão recente ganha influência à medida que há novos jogos.

## Interface e validação

A aba **Jogadores > Projeções** permite selecionar a temporada-alvo (temporada corrente estimada ou a seguinte), mostra a temporada-base efetivamente usada e a diferença entre a média sazonal de PTS/REB/AST e a projeção. Se a temporada imediatamente anterior à temporada-alvo não existir no banco, o sistema usa a temporada mais recente disponível. A tela **Qualidade do Modelo** compara os erros absolutos médios (MAE) do modelo híbrido com os MAEs de referência anual para pontos, rebotes e assistências. O resultado deve ser avaliado em validação temporal por datas completas; não se deve presumir que a combinação melhora todas as métricas sem conferir os números.

## Limite conhecido

As mudanças de função/time só podem ser inferidas com os dados disponíveis. Antes de o novo time disputar partidas ou de a troca ser registrada na fonte, não há informação suficiente para medir a nova função ofensiva sem uma entrada explícita de elenco/rotação.
