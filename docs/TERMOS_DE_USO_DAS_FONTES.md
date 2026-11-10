# Fontes de dados: o que revisar nos termos de uso

Antes de manter o app **público**, revise os termos de uso e as políticas de cada fonte
abaixo. Esta lista só relaciona o que o código acessa; **não** é uma conclusão jurídica.

| Fonte | Onde o código acessa | O que conferir |
|---|---|---|
| NBA (nba.com, cdn.nba.com, stats.nba.com via `nba_api`) | `src/nba_schedule.py`, `src/shot_connector.py`, `src/season_sync.py`, páginas de coleta | Termos de uso do nba.com; regras para uso automatizado e redistribuição de dados e de arremessos |
| ESPN (`site.api.espn.com`, espn.com) | `src/live_*`, calendário e boletins | Termos de uso da ESPN; redistribuição de placares e boletins de lesões |
| SportsDataverse / `sportsdataverse-data` (Releases públicos no GitHub) | `src/history_sources.py`, `src/injuries.py` | Licença do conjunto de dados e dos arquivos parquet |
| balldontlie, API-Sports, RapidAPI NBA, The Odds API | `src/provider_settings.py`, `src/ui/live.py` | Só se você usar chaves próprias; termos do plano contratado. A versão online não usa chaves |
| GitHub (Releases e Actions) | `data-refresh.yml`, `daily-picks.yml` | Limites de uso do Actions e de armazenamento de Releases para repositórios públicos |
| Streamlit Community Cloud | publicação do app | Termos do serviço e regras para apps públicos |

Pontos práticos: o pacote publicado no Release é **público** e contém dados derivadas dessas
fontes; a versão online exibe o aviso de que as probabilidades são experimentais e não são
recomendação de aposta.
