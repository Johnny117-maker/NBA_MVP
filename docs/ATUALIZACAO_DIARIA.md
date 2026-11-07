# Atualização ao fim do dia

Objetivo: a base de jogos sempre inclui os resultados da noite anterior, mesmo sem o
aplicativo aberto. Os jogos da NBA terminam de madrugada no Brasil, e as fontes públicas
publicam os resultados com algumas horas de atraso.

## No seu computador

```text
AGENDAR_ATUALIZACAO_DIARIA.bat            cria a tarefa do Windows
AGENDAR_ATUALIZACAO_DIARIA.bat remover    desfaz
ATUALIZAR_DIARIO.bat                      executa agora, sem janela de pausa
```

A tarefa roda às 07:00 e às 12:00, e também ao entrar no Windows. Se o computador estiver
desligado no horário, ela roda assim que ele ligar. Cada execução grava o resultado em
`data\atualizacao_diaria.log`.

Cada execução (`scripts/update_daily.py`):

1. força uma consulta nova ao arquivo público da temporada, ignorando o cache de uma hora;
2. importa os jogos encerrados, com as mesmas validações do monitor do aplicativo;
3. confere o dia anterior (fuso Eastern): todos os jogos da fonte terminaram e estão na base?
4. se não estiver, espera 20 minutos e repete, até 3 tentativas;
5. compara com os resultados os palpites salvos que ainda não foram avaliados.

Códigos de saída: `0` base atualizada; `2` a fonte ainda não publicou todos os jogos do dia
anterior (a tarefa seguinte tenta de novo); `3` nenhuma fonte respondeu. O resumo também
aparece em **Dados e Atualizações**.

Limites:

- O computador precisa ligar em algum momento do dia. Não há serviço em segundo plano.
- Em redes que bloqueiam NBA e ESPN diretamente, a atualização depende do arquivo
  SportsDataverse/ESPN, que atrasa algumas horas em relação ao fim dos jogos.
- A tarefa foi escrita e testada na parte Python (testes automatizados e uma execução real
  contra a fonte pública), mas o script do Agendador do Windows não pôde ser executado no
  ambiente de desenvolvimento, que é Linux. Se algo falhar ao agendar, rode
  `ATUALIZAR_DIARIO.bat` manualmente e avise.
- O executável do Windows guarda os dados em `%LOCALAPPDATA%\NBAAnalyticsLab`. Para usar a
  tarefa com ele, defina a variável de ambiente `NBA_DATA_HOME` com essa pasta.

## No GitHub

A rotina `Salvar palpites diarios` já roda a cada duas horas e sincroniza a temporada antes de
gerar palpites. A mudança: o palpite de um jogo só é preservado nas **últimas 6 horas antes do
início**. Antes, a primeira execução do dia (de madrugada) já preservava o palpite da noite
seguinte, e como a captura nunca é substituída, ele ficava com um histórico que ainda não
tinha os jogos da noite anterior. Foi o caso de PHI @ CLE em 06/11: captura às 03:54 de
Brasília, com histórico até 04/11.

Jogos fora da janela aparecem no relatório em `waiting` (com o horário em que a captura
começa) e não contam como perdidos. Com execuções a cada duas horas, ao menos duas caem dentro
da janela de cada jogo. Se todas falharem, o jogo continua sendo registrado como
"Janela pré-jogo perdida", como antes.
