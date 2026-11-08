# Histórico de mudanças

Texto movido do antigo `README.md`, sem alterações. As seções mais novas vêm primeiro.
Para instalar e usar o projeto, veja o [README](README.md).

## Previsão de times mais precisa e base atualizada todo dia

O modelo de times agora usa **Elo com margem de vitória**: o vencedor e o placar saem da
mesma margem prevista, então nunca se contradizem. Em 2.592 jogos de temporadas que não
participaram do ajuste, o acerto subiu de 64,8% para 67,6% e o erro probabilístico caiu.
O ganho é menor no começo da temporada e não elimina o acaso de um jogo (veja os limites).
[Método, evidência e limites](docs/MODELO_TIMES_ELO.md).

`AGENDAR_ATUALIZACAO_DIARIA.bat` cria uma tarefa do Windows que importa os resultados da
noite anterior às 07:00 e às 12:00, mesmo com o aplicativo fechado. Na nuvem, o palpite de
cada jogo agora é preservado nas últimas 6 horas antes do início, já com o histórico do dia
anterior. [Como funciona](docs/ATUALIZACAO_DIARIA.md).

## Jogos do dia com todos os destaques visíveis (1.6.1)

Em **Jogos do dia**, os destaques agora abrem mostrando todos os atletas elegíveis.
Use o campo **Atletas na lista** para reduzir a quantidade ou filtre por nome, perfil e estatística.

## Qualidade, explicação e comparação automática (1.6.0)

O sistema preserva a previsão antes do jogo, busca os resultados das datas pendentes
e compara cada jogador com o que realmente aconteceu. Os resultados confirmados
também ficam no GitHub e podem ser importados em outro computador; correções geram
novas versões sem alterar o palpite original.
[Como funciona o ciclo automático](docs/CICLO_AUTOMATICO_DOS_PALPITES.md).

**Desempenho** separa capturas pré-jogo de teste histórico independente. As explicações
mostram a linha exata, o histórico preservado e os pesos reais dos modelos.
Over/Under é avaliado por Brier, log loss e calibração, com empates tratados separadamente.
O teste disponível avaliou 4.090 jogos de atletas em 221 partidas; os ganhos de erro
ficaram abaixo do critério de vantagem prática. As probabilidades continuam experimentais.
[Protocolo, resultados e reprodução](docs/QUALIDADE_DAS_PREVISOES.md).

## Resultados, central da partida e atualização do programa (1.5.0)

Compare os palpites originais com os resultados, consulte a calibração das probabilidades
e acompanhe placar, disponibilidade e defesa na **Central da partida**. Cada palpite
pode ser explicado e comparado com outra linha sem alterar o registro pré-jogo.
O modelo de minutos só é ativado quando supera a referência na validação temporal.
Boletins de lesões vencidos suspendem novos palpites individuais.

**Sistema e atualizações** prepara pacotes menores, sem repetir a base histórica,
e preserva a versão anterior. [Critérios, resultados e funcionamento](docs/MELHORIAS_1_5.md).

## Interface simples e aprendizado pelos resultados (1.4.0)

A abertura prioriza a rodada de hoje. O menu destaca cinco caminhos: Início, Jogos,
Palpites, Ao vivo e Histórico. Projeções já salvas aparecem prontas, sem exigir outro
cálculo. As ferramentas detalhadas continuam acessíveis em grupos no menu lateral.

Após os jogos, o sistema compara as previsões originais com os resultados confirmados.
O XGBoost treina novamente com dados novos, e uma camada de feedback testa ajustes da
combinação Bayes/ML em datas posteriores. Ajustes sem melhoria ficam de fora. Consulte
**Laboratório → Aprendizado automático** e [as regras e ideias de UX](docs/UX_E_APRENDIZADO.md).

Aplicativo de análise da NBA com histórico local, atualização da temporada, projeções de jogadores e comparação entre previsões e resultados.

## Gravação diária automática — versão 1.3.0

O GitHub Actions gera e salva os palpites a cada duas horas, mesmo com o PC desligado.
O **Histórico diário** importa as capturas com SHA-256 e preserva os registros locais.
Consulte [configuração, cobertura e limites](docs/PALPITES_AUTOMATICOS_GITHUB.md).

## Defesa e disponibilidade — versão 1.2.0

A versão 1.2.1 exclui lesionados e atletas em dúvida de **Palpites de hoje**,
antes do ranking e da geração, com nova conferência quando o boletim muda.

- Índice defensivo de 0 a 100 com pesos e amostra mínima ajustáveis.
- Mapas de arremessos cedidos, comparação por região e evolução da defesa.
- Visão do marcador: produção dos atacantes e referência contra outros defensores.
- Boletim de lesões automático, com fonte, referência, aviso de defasagem e status nos destaques de hoje.

Consulte os critérios, fontes e limites em [Índice defensivo e lesões](docs/INDICE_DEFENSIVO_E_LESOES.md).

## Correções de compatibilidade e contexto defensivo — 21/10/2026

A tela **Qualidade do Modelo** agora continua a funcionar com logs de treinamento antigos que ainda não têm as métricas comparativas da temporada-base. A previsão de pontos também aplica um ajuste pequeno e limitado para considerar o defensive rating do adversário; consulte [`docs/CORRECAO_FALHAS_TESTES_2026-10-21.md`](docs/CORRECAO_FALHAS_TESTES_2026-10-21.md) para detalhes e limitações.

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
