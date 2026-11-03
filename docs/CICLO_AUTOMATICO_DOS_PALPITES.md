# Ciclo automático dos palpites e resultados

O GitHub Actions executa a rotina a cada duas horas, sem depender do computador
aberto. O horário agendado pode sofrer atrasos do próprio GitHub. O coletor local
continua consultando as fontes enquanto o aplicativo estiver aberto.

1. Atualiza a temporada e consulta os jogos e o boletim de disponibilidade.
2. Treina ou reutiliza o modelo compatível com a base anterior à partida.
3. Salva a primeira previsão pré-jogo de todos os jogadores elegíveis, com pontos,
   rebotes, assistências, faixas, linhas, probabilidades, modelo e horário.
4. Busca os resultados das datas com previsões ainda pendentes. A fila consulta
   até três datas anteriores por ciclo, priorizando a mais recente e fazendo rodízio
   nas antigas, além do dia atual. Uma data sem resposta não bloqueia as demais.
5. Confere o placar, a soma dos pontos e os minutos das duas equipes antes de
   registrar o resultado de cada jogador. Ausência não é zero de produção nem Under vencido.
6. Compara previsto e realizado, atualiza as métricas e testa ajustes de aprendizado
   somente com resultados finais confirmados e datas anteriores à nova previsão.

## Registros permanentes no GitHub

As previsões ficam em `archive/days` na branch privada `codex/daily-archive`.
Os resultados ficam separadamente em `archive/results`. Cada arquivo de resultado
aponta para o SHA-256 da captura original. Uma correção gera um novo arquivo;
os arquivos anteriores e a previsão permanecem preservados.

A publicação dos resultados é atômica e só aceita capturas já publicadas com o
mesmo hash. O índice aponta para a versão atual. O publicador processa até 400
capturas com resultados alterados por execução, retomando as restantes no próximo lote. A sincronização
local importa em lotes e continua nas próximas execuções, sem duplicar resultados.

Com o aplicativo aberto, a sincronização a cada 15 minutos importa previsões e
resultados. Um computador com acesso bloqueado às APIs NBA/ESPN ainda pode comparar
os palpites com os resultados obtidos pelo GitHub, desde que tenha acesso ao GitHub
e autenticação de leitura no repositório privado. JSONs e ZIPs também podem ser
importados no Histórico diário: primeiro as capturas, depois os resultados vinculados.

Resultados remotos recebidos não são substituídos por uma base local antiga.
A rotina central pode registrar correções posteriores após nova conferência do box score.

## Como acompanhar

- **Histórico diário:** captura original e resultado de cada partida/jogador.
- **Desempenho → Capturas pré-jogo:** erro, cobertura, Over/Under e comparação dos modelos.
- **Desempenho → Teste histórico independente:** teste reconstruído, separado da avaliação prospectiva.
- **Arquivo automático do GitHub:** sincronização, importação e link da execução.

O relatório da execução inclui `results_added`, `result_days_pending`,
`result_publication` e erros das fontes. Quando os dados finais ainda não chegaram,
o resultado permanece pendente e a fila tenta novamente. Falhas de rede não criam
resultados estimados nem palpites retroativos. Boletim vencido ou atleta indisponível
continua impedindo novos palpites individuais.

Os resultados antigos sem marcação de conferência final são reavaliados antes de
alimentar novas métricas e o aprendizado. As previsões originais não são recalculadas
com o modelo novo para simular um acerto que não havia sido previsto.
