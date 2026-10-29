# Uma experiência mais simples

## Ideias aplicadas nesta versão

- **Começar pelo dia:** início com jogos, situação e previsões salvas. Estatísticas da temporada ficam em uma opção de consulta.
- **Cinco caminhos principais:** Início, Jogos, Palpites, Ao vivo e Histórico. Jogadores, defesa e ferramentas técnicas ficam em grupos secundários que abrem quando usados.
- **Resultado pronto antes dos ajustes:** Palpites mostra as projeções já salvas e permite filtrar por jogo. O cálculo adicional fica opcional.
- **Uma tarefa por vez:** escolher Jogadores ou Confrontos evita treinar o modelo de times enquanto a pessoa consulta jogadores.
- **Palavras familiares:** Pontos, Rebotes e Assistências por extenso; uma explicação curta de Over/Under; horário de Brasília visível.
- **Explicar o aprendizado:** o Laboratório informa se faltam resultados, se o modelo base foi mantido ou se um ajuste passou na validação.

## Próximas ideias

1. Favoritos locais: acompanhar uma lista pequena de jogadores e times.
2. Tela de partida única: placar, disponibilidade, projeções e marcações reunidos.
3. Comparação visual: um gráfico simples de previsto versus realizado nos últimos jogos.
4. Filtros persistentes: lembrar estatística e time preferidos neste computador.
5. Resumo da rodada encerrada: mostrar o que foi previsto, quem participou e qual foi o erro, com link para o registro original.

# Aprender com os resultados

O XGBoost já identifica mudanças no histórico por hash e treina novamente quando chegam dados novos. A nova camada de feedback aprende também com **previsões reais salvas antes das partidas**, comparando-as aos boxscores confirmados.

O ciclo automático é: importar capturas anteriores → atualizar jogos encerrados → resolver resultados da partida exata → avaliar ajustes → usar os ajustes aprovados nas próximas previsões. Funciona no monitor local e na rotina GitHub Actions. O relatório diário do GitHub preserva a situação do aprendizado, importada pelo aplicativo.

## Regras

- Janela recente de 90 dias, com uma observação por jogo/jogador/estatística. A captura GitHub tem preferência quando também existe uma local.
- Resultados do próprio dia alvo e dias futuros ficam fora. Atletas que não participaram e resultados ausentes não viram zero.
- Pelo menos 120 resultados por estatística e 8 datas. A seleção usa os primeiros 70% das datas; a avaliação usa as datas posteriores, com pelo menos 40 resultados e 3 datas.
- O ajuste pode mudar o peso Bayes/XGBoost e corrigir um desvio médio robusto. A correção aditiva é limitada a 3 pontos ou 1,5 rebote/assistência, com redução para amostras menores.
- Só é adotado se reduzir o erro absoluto médio em pelo menos **2% e 0,02 unidade** no período posterior. Caso contrário, mantém a combinação base.
- Modelo, ajuste, amostra e erros são registrados nas novas capturas. As previsões antigas continuam imutáveis.
- O erro médio avalia a quantidade prevista. Isso não prova calibração das probabilidades Over/Under nem garante melhoria futura.

Não há ganho medido a anunciar enquanto não existir amostra suficiente. A tela mostra essa condição explicitamente.

Referências: [validação temporal do scikit-learn](https://scikit-learn.org/stable/modules/cross_validation.html#time-series-split) e [API oficial do XGBoost](https://xgboost.readthedocs.io/en/stable/python/python_api.html).
