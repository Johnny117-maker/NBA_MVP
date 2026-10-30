# Melhorias da versão 1.5.0

## Resultado dos palpites

**Desempenho → Palpites automáticos** compara as capturas pré-jogo preservadas
com os resultados confirmados. Mostra erro médio, viés, cobertura da faixa P10–P90,
calibração das probabilidades e comparação de modelos na mesma amostra.
Partidas sem resultado e jogadores que não participaram não viram zeros artificiais.
A calibração usa linhas de meio ponto para evitar confundir empate com erro.

## Minutos esperados

O XGBoost de minutos usa somente histórico anterior à partida: médias recentes,
variabilidade, descanso, mando e uso. A escolha da mistura usa uma etapa temporal
de calibração e a avaliação final usa datas posteriores. Só substitui a referência
se melhorar pelo menos 0,15 minuto e 2% no erro médio nas duas etapas, sem prejudicar
as projeções de pontos, rebotes e assistências além da tolerância documentada no código.

Na avaliação local com 40 mil registros históricos, o erro da referência foi
5,373 minutos e o candidato chegou a 5,295 em 7.867 registros de validação.
O ganho ficou abaixo dos critérios: a referência foi mantida. A existência do novo
modelo não significa que ele foi aprovado. O estado e os resultados ficam no manifesto
do modelo. As estimativas continuam condicionadas à participação do atleta.

## Explicação e comparação de linhas

**Palpites → Explicar um palpite e comparar uma linha** mostra projeção, faixa,
minutos, forma recente e contexto disponível antes do jogo. A comparação calcula
mais, menos e empate para a linha informada, sem alterar a captura original.
Capturas antigas sem parâmetros suficientes informam a limitação.
O contexto não é apresentado como uma explicação causal do resultado.

## Qualidade e disponibilidade

A interface mostra fonte, referência e defasagem dos dados. Um boletim de lesões
com mais de 48 horas ou mais de dois dias de referência bloqueia novos palpites
individuais. Capturas históricas permanecem disponíveis para auditoria.
Observações reais de uma partida em andamento continuam visíveis.
As tentativas de coleta NBA e ESPN permanecem habilitadas, inclusive para outras redes.

## Central da partida

Uma tela reúne resumo e placar, palpites, disponibilidade, defesa e observações
ao vivo. O mapa defensivo é carregado quando solicitado. Marcações individuais só
aparecem quando a fonte publicou os confrontos: ausência de dados não vira uma
atribuição de defensor inventada.

## Atualização do executável

**Sistema e atualizações** consulta a última versão estável no repositório privado.
A autenticação usa a configuração local do GitHub; chaves não acompanham o pacote.
O download é conferido pelo tamanho e SHA-256 publicado no GitHub antes da extração.

O arquivo `NBAAnalyticsLab-1.5.0-program-Windows-x64.zip` contém o programa e suas
bibliotecas, sem a base histórica. Requer um perfil existente em
`%LOCALAPPDATA%\NBAAnalyticsLab`. Na primeira instalação, use o pacote completo.
A versão preparada fica em `updates/<versão>` no perfil, separada do programa ativo.
Depois da preparação, atualize o atalho, feche a janela e abra pelo ícone.
O atalho anterior pode ser restaurado pela mesma tela enquanto a pasta anterior existir.

Os dados pessoais não são sobrescritos. A coleta e a importação de dados continuam
separadas da atualização do programa. O instalador portátil não atualiza a si próprio
enquanto está em execução.
