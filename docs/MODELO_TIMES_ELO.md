# Modelo de times: Elo e previsão por margem

Substitui a regressão logística sobre médias de dez jogos. Motivo: essas médias misturavam
o fim da temporada anterior com o começo da atual e não corrigiam a força do adversário, o
que deixava as previsões instáveis nas primeiras semanas.

## Como funciona

- **Elo** (`src/team_strength.py`): força acumulada de cada time, que sobe mais ao vencer
  adversários fortes e por placares largos, e volta 40% em direção à média a cada nova
  temporada (os elencos mudam). Só usa jogos anteriores ao previsto.
- **Margem** (`src/model.py`): regressão (Ridge) da margem do mandante sobre diferença de Elo,
  Net Rating, forma recente e descanso.
- **Vencedor**: chance de vitória = Φ(margem prevista / σ), com σ estimado nos resíduos
  (cerca de 14 pontos).
- **Placar**: modelo do total de pontos (ataque e defesa absolutos) combinado com a margem:
  cada time recebe `(total ± margem) / 2`. Vencedor e placar vêm da mesma margem e não se
  contradizem. O favorito nunca perde no placar previsto.

Parâmetros do Elo (K=15, mando=45, regressão=0,6) foram escolhidos só com 2021-22 a 2023-24.

## Evidência

Validação temporal: cada mês é previsto só com jogos anteriores. Teste "cego" (2024-25,
2025-26 e 2026-27 até 06/11, 2.592 jogos), que não participaram da escolha dos parâmetros:

| | Acerto | Brier | Log loss | Erro médio da margem |
| --- | ---: | ---: | ---: | ---: |
| Modelo anterior | 64,8% | 0,2160 | 0,6302 | 11,55 pts |
| Elo e margem | 67,6% | 0,2074 | 0,6019 | 11,17 pts |

Ganho de acerto: +2,8 pontos percentuais (IC 95% de +1,3 a +4,4). Ganho de log loss: 0,028
(IC 95% de 0,015 a 0,044), por bootstrap pareado por jogo.

O mesmo código de produção, com o modelo congelado no início de cada temporada (mais difícil
que retreinar todo dia):

| Temporada | Acerto antes → depois | Log loss antes → depois |
| --- | --- | --- |
| 2023-24 | 62,9% → 65,1% | 0,638 → 0,612 |
| 2024-25 | 65,8% → 66,7% | 0,659 → 0,608 |
| 2025-26 | 65,5% → 68,8% | 0,617 → 0,596 |

### O que o ganho não é

- **Começo de temporada** (até 12 jogos por time, 534 jogos): as probabilidades melhoram
  (log loss 0,659 → 0,607), mas o acerto do vencedor não (65,9% → 64,8%, dentro do ruído).
- **Temporada atual** (132 jogos até 06/11): o ganho de log loss é pequeno (0,005), numa amostra
  curta demais para concluir.
- Um jogo isolado não prova nada. Em 06/11, PHI @ CLE terminou 95 x 119. O modelo anterior
  dava PHI 56,8%, e o novo daria CLE 57,6%, com placar previsto de 114,6 x 112,0. A
  margem real (24 pontos) é cerca de 1,7 desvio-padrão da distribuição de margens da NBA:
  nenhum modelo de resultado prevê isso. Todos os titulares dos 76ers jogaram; foi uma noite
  ruim, com os titulares poupados na goleada.

## Limites conhecidos

- Não há histórico de lesões e escalações para validar. Um desfalque de estrela só entra
  na previsão depois que os resultados mudam o Elo.
- O erro típico de uma margem prevista continua em cerca de 11 pontos. O modelo melhora a
  escolha do favorito e a qualidade das probabilidades, não elimina o acaso do jogo.
- Probabilidades continuam experimentais.

## Reprodução

`python scripts/audit_models.py --as-of AAAA-MM-DD --output reports/model_audit.json` compara,
por temporada completa, o modelo atual com a logística anterior (`legacy_*`) na sua base.
