# Palpites diários sem abrir o aplicativo

A versão 1.3.0 inclui a rotina **Salvar palpites diarios**, executada por GitHub
Actions a cada duas horas, no minuto 17 (UTC). A geração ocorre no GitHub, mesmo
com o PC desligado. Não depende de deixar o Streamlit aberto nem de servidor
próprio. O workflow também aceita execução manual pela aba Actions.

## O que é preservado

Cada jogo elegível recebe a primeira captura pré-jogo, com PTS, REB, AST, faixas
e referências Over/Under de todos os atletas elegíveis, não apenas três por time.
A seleção exige histórico anterior, pelo menos três partidas, média recente de
dez minutos, participação no histórico da temporada e recência de até 45 dias.
Lesionados, suspensos e dúvidas informadas pelo boletim ficam de fora. Sem boletim
válido, não se geram novos palpites individuais. Quando houver histórico de times
suficiente, a captura também inclui favorito, probabilidades e placar previsto.

O modelo usa apenas jogos anteriores ao dia NBA (ET). A captura é conferida
novamente depois do cálculo para impedir gravação após o início. Uma rodada
perdida não é reconstruída posteriormente como se fosse uma previsão original.

## Armazenamento e auditoria

O repositório permanece **privado**. A branch `codex/daily-archive` armazena:

- `archive/index.json`: índice das datas disponíveis;
- `archive/days/AAAA-MM-DD/manifest.json`: cobertura, pendências e execução;
- `archive/days/AAAA-MM-DD/VISITANTE_at_MANDANTE.json`: captura com SHA-256.

As primeiras capturas não são substituídas por execuções posteriores. Cada
publicação atualiza a referência Git atomicamente e mantém a cadeia de commits.
O relatório distingue jogos salvos, faltantes e janelas pré-jogo já perdidas.
Relatórios HTML também ficam como artifacts da execução por 30 dias; os JSONs
duráveis ficam na branch, sem depender da retenção de artifacts.

A base `prediction-seed-v1` contém só estatísticas públicas e é conferida por
SHA-256. Não inclui previsões locais, chaves, relatórios pessoais ou modelos de
usuários. A rotina usa o GITHUB_TOKEN temporário do próprio workflow. O cache
diário reduz downloads e treinos repetidos; o cache não é o arquivo durável.

## Consultar no sistema

Em **Histórico diário**, selecione a data e abra **Arquivo automático do GitHub**.
A sincronização acontece a cada 15 minutos com o sistema aberto; o botão permite
buscar imediatamente a data escolhida. O importador verifica hashes e datas.

As capturas automáticas e as gravações locais são armazenadas separadamente.
A visualização padrão prefere o registro GitHub mais completo para cada jogo,
sem apagar o original local. A seleção de origem permite consultar só os locais
ou todas as capturas. IDs locais negativos são reconciliados por nome completo
e equipe ao resolver resultados importados; não são tratados como IDs NBA.

Por ser privado, o histórico exige acesso ao repositório. O app aproveita uma
autenticação local do GitHub CLI já existente, quando disponível. Em outro PC,
pode usar `NBA_GITHUB_ARCHIVE_TOKEN` ou `[archive].github_token` no arquivo
protegido `.streamlit/secrets.toml`, com Contents somente leitura. Não envie o
token ao chat nem o inclua em commits. Também é possível baixar os JSONs pelo
navegador autenticado e importá-los, sem instalar GitHub CLI.

## Limites operacionais

GitHub Actions e as fontes externas podem atrasar ou falhar. O agendamento não é
uma garantia de execução no segundo exato. Confira a execução e a cobertura na
aba Actions; falhas e falta de dados ficam registradas, sem previsões inventadas.
As quotas de Actions da conta continuam aplicáveis. Consultas NBA/ESPN e fontes
alternativas continuam habilitadas.

Referência: [execuções agendadas do GitHub Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
