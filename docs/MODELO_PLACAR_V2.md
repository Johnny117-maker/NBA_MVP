# Modelo de placar v2 — 27/10/2026

O modelo de placar validado na auditoria agora é usado por `predict_game`,
compartilhado pela Central de Partida, Jogos do Dia e Palpites. Cada regressão
Ridge mantém `alpha=2.0`, com padronização ajustada somente no treinamento.

## Entradas e contexto da previsão

As regressões de pontos da casa e do visitante passam de cinco para onze entradas:

- Diferenças de net rating, forma recente, descanso, ataque e defesa.
- Rating ofensivo e defensivo de cada time, em valores absolutos.
- Média dos pontos marcados por cada time nos últimos dez jogos anteriores.

As médias de pontos excluem toda a data do confronto, inclusive em bases com
mais de um jogo do mesmo time no mesmo dia. Demonstrações e CSVs continuam
aceitos: as novas médias são calculadas a partir dos placares históricos, sem
exigir novas colunas no arquivo enviado.

O classificador de vitória continua usando suas cinco diferenças e a regressão
logística. Seus fatores explicativos e a simulação de temporada conservam esse
esquema. A mudança de placar não substitui os modelos individuais de jogadores
nem os modelos de zonas de arremesso.

Dois problemas de contexto também foram corrigidos:

- O primeiro rating de um time usava a média de toda a base, incluindo jogos
  futuros. Agora usa um prior fixo de 110; acrescentar resultados futuros não
  altera esse contexto inicial.
- O snapshot de um time fazia outra média sobre ratings que já eram médias
  pré-jogo. Na base real ele passa a usar os ratings observados dos últimos
  dez jogos. Há um teste de igualdade entre as entradas de um jogo histórico
  e o snapshot construído apenas com jogos anteriores a ele. Nos CSVs legados
  sem ratings observados, preserva-se o comportamento anterior dessas colunas.

O rating observado é o valor oficial quando coletado e, nos demais jogos, a
aproximação por pontos marcados/sofridos. A cobertura oficial continua pequena;
esta ativação não acrescenta dados de posse de bola, lesões ou escalações.

## Comparação após a correção temporal

O [relatório agregado](../reports/model_promotion_2026-10-27.json) foi gerado com
9509 jogos, em consulta somente leitura ao banco. Para cada temporada, os pesos
foram ajustados somente em datas anteriores ao início dela. O contexto de cada
partida usa resultados disponíveis antes da própria data, incluindo partidas
anteriores da temporada de teste. Não houve busca de parâmetros.

As duas versões da comparação usam os mesmos dados e o prior corrigido. A
referência antiga mantém somente as cinco variáveis relativas; a versão atual
usa as onze entradas. Os números são MAE de pontos por time, média entre casa
e visitante; menor é melhor.

| Temporada de teste | Jogos | Anterior | Placar v2 | Redução do erro |
| --- | ---: | ---: | ---: | ---: |
| 2023-24 | 1230 | 10,071 | 9,415 | 6,51% |
| 2024-25 | 1225 | 9,871 | 9,403 | 4,74% |
| 2025-26 | 1225 | 10,110 | 9,689 | 4,16% |

A auditoria original permanece arquivada em
`reports/model_audit_2026-10-27.json`. Seus campos de candidato e de produção
refletem o código anterior à ativação. O script atualizado agora compara a
produção v2 com a referência relativa antiga explicitamente identificada.

As temporadas acima também embasaram a escolha do candidato: os ganhos são
evidência histórica de comparação, não uma avaliação independente após a
seleção nem uma garantia de desempenho em partidas futuras. A base local
termina em 12/04/2026; os avisos de dados antigos continuam relevantes.

## Treinamento, identificação e validação

`train_models` avalia aproximadamente os 20% finais dos jogos, mantendo datas
completas fora do treinamento de avaliação. Depois reajusta os modelos com todo
o histórico recebido para produzir as próximas previsões. Os intervalos de
placar usam resíduos dessa avaliação temporal, mantendo a fórmula existente;
a cobertura nominal de 80% ainda precisa de uma auditoria específica.

Os novos logs de times registram `score_model_version=2` e
`score_feature_count=11`. A página Qualidade do Modelo identifica a versão
somente quando o registro contém essa informação; registros antigos não são
renomeados como se fossem avaliações do modelo novo.

A ativação foi registrada no treinamento local 16, em 27/10/2026, com os 9509
jogos reais. Na avaliação da parte final dessa base, o MAE foi de 9,725 pontos
para a casa e 9,463 para o visitante. Esse recorte é diferente das temporadas
completas da tabela acima. O servidor foi reiniciado para limpar os modelos
anteriores mantidos em memória.

Com o ambiente virtual ativado no PowerShell:

```powershell
python scripts/retrain_models.py --team-only
python scripts/audit_models.py --as-of 2026-10-27 --output reports/model_promotion_2026-10-27.json
```

O primeiro comando treina e registra somente times. O segundo consulta os dados
sem alterar o banco e permite repetir a comparação. O fluxo padrão de
`RETREINAR_MODELOS.bat` continua disponível para a avaliação completa dos modelos.

Testes cobrem a exclusão de resultados da própria data, a independência de
resultados futuros, a correspondência do contexto entre treinamento e previsão,
a separação temporal por datas, o novo esquema de placar, o esquema do
classificador e o registro seletivo de treinamento. O problema de prior futuro
nos modelos de zonas, apontado na auditoria original, permanece pendente.

Verificação da ativação: 285 testes passaram; Ruff sem erros; mypy sem erros
nos 51 arquivos de produção. A tela de qualidade foi conferida no navegador
com o registro da versão 2 e os novos valores de MAE.
