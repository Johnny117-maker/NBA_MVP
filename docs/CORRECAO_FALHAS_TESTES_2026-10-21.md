# Correção das falhas nos testes — 21/10/2026

## 1. Compatibilidade com logs antigos na tela de qualidade

A página `pages/6_Qualidade_Modelo.py` tentava formatar `pts_season_baseline_mae`, `reb_season_baseline_mae` e `ast_season_baseline_mae` antes de verificar se essas métricas existiam. Logs de treinamento criados por versões anteriores não contêm essas chaves, e isso causava `KeyError` ao abrir a página.

A página agora só cria os cartões comparativos quando as três métricas existem. Quando o log é antigo, apresenta uma mensagem informativa e mantém o restante dos indicadores visível. Um novo retreinamento passa a gerar as métricas comparativas para registros novos.

## 2. Ajuste explícito para a defesa adversária

O teste `test_opponent_def_rating_shifts_the_prediction` detectou que o regressor de pontos podia produzir o mesmo valor diante de diferentes ratings defensivos — especialmente quando o modelo de árvores não aprendia uma separação para essa variável no conjunto de treino.

Foi adicionada uma camada de contexto conservadora ao resultado de pontos:

- rating defensivo acima da média de referência (mais pontos permitidos) aumenta moderadamente a projeção;
- rating abaixo da média (defesa mais forte) reduz moderadamente a projeção;
- o ajuste é de 0,25% por ponto de rating, limitado a +/-10%;
- rebotes e assistências não são alterados por este ajuste;
- os intervalos por quantis recebem o mesmo ajuste que a previsão central.

A média de referência usada na avaliação interna é calculada apenas no conjunto de treino. Esta camada é um prior explícito e interpretável, não uma relação causal comprovada; o seu benefício deve ser acompanhado em backtests temporais e poderá ser recalibrado conforme o erro real.

## 3. Testes e limitações da validação

Foram adicionados dois testes isolados em `tests/test_opponent_defense_adjustment.py`: um verifica direção e limites do ajuste; o outro valida a integração no pipeline de previsão e confirma que o ajuste não altera rebotes e assistências.

Resultado local: **2 testes isolados aprovados** e arquivos alterados compilados com `py_compile`. Não foi possível executar aqui os testes de interface `AppTest`, pois Streamlit não está instalado no ambiente; o conjunto completo deve ser executado no Windows com `EXECUTAR_TESTES.bat`.
