# Jogos do Dia e jogadores em destaque

A página `pages/7_Jogos_do_dia.py` lista os confrontos do calendário NBA selecionado, exibe horários em Brasília e ET, status e arena quando disponíveis. A camada `src/daily_games.py` calcula a forma dos jogadores com médias dos últimos cinco jogos, compara a pontuação recente com a média da temporada mais recente e identifica perfis como cestinha, reboteiro, criador e atleta em alta.

## Probabilidade experimental de vitória

Quando há dados reais de jogos coletados, a página mostra uma probabilidade aproximada para os dois times usando o net rating recente e um ajuste simples de mando de quadra. A estimativa é limitada a 5%–95%, não usa odds e não deve ser interpretada como previsão calibrada. Sem histórico suficiente, a probabilidade é omitida/indicada como indisponível.

## Limitações importantes

- Para mostrar destaques reais, execute a coleta em **Dados e Atualizações**; a página não inventa nomes nem usa atletas sintéticos como se fossem reais.
- O banco pode estar desatualizado durante a offseason; confira a data de atualização.
- A base atual não confirma lesões, titulares ou restrições de minutos. O destaque estatístico pode não jogar.
- O calendário usa a NBA oficial e tem fallback ESPN, conforme `src/nba_schedule.py`.

## Validação realizada

- Compilação sintática de `app.py`, páginas, `src` e testes (`compileall`).
- Testes manuais de fumaça para médias recentes, ranking, filtro de jogadores inativos, aliases de times, conversão de horário e rótulos de status.
- A suíte pytest não pôde ser executada no ambiente de edição porque a dependência `nba_api` não está instalada e a rede não permitiu instalá-la.
