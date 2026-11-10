# Publicar o app online (Streamlit Community Cloud)

A versão online é **somente leitura**: não coleta dados, não grava previsões e não recebe
nenhum token. Quem coleta e publica os dados é o GitHub Actions (`data-refresh.yml`); o app
apenas baixa o pacote publicado e o exibe.

```text
GitHub Actions (data-refresh)  ──publica──▶  Release "data-latest"  ◀──baixa──  App no Streamlit
 coleta + gera pacote enxuto                 manifest.json + .tar.gz              somente leitura
```

O programa local e o executável do Windows **não mudam**: tudo que é específico da nuvem só
liga com `NBA_DEPLOY_MODE=cloud`.

## Passo a passo

1. **Repositório público.** O Release precisa ser baixável sem login. Confirme em
   *Settings → General → Danger Zone* que o repositório está público.
2. **Rode o `data-refresh` uma vez antes de publicar o app.** Em *Actions → Atualizar dados
   publicados → Run workflow* (branch `main`). Ao terminar, abra *Releases → Dados publicados
   (`data-latest`)* e confira os arquivos:
   `manifest.json`, `nba-serving-<versão>.tar.gz`, `nba-full.tar.gz` e `nba-full.tar.gz.sha256`.
   Se a execução falhar, veja o log: uma issue `falha-atualizacao-dados` é aberta
   automaticamente (uma só, sem duplicar).
3. **Crie o app** em <https://share.streamlit.io> → *Create app* → *Deploy a public app from GitHub*:
   - Repository: este repositório;
   - Branch: `main`;
   - Main file path: `app.py`;
   - Advanced settings → Python version: **3.12**.
4. **Secrets** (*Advanced settings → Secrets*), exatamente:

   ```toml
   NBA_DEPLOY_MODE = "cloud"
   ```

   Não coloque tokens. Se o repositório dos dados for outro, acrescente
   `NBA_ARCHIVE_REPOSITORY = "dono/repositorio"`.
5. **Deploy.** O `requirements.txt` da raiz é o usado (ele não traz PySide6, PyInstaller nem
   nada do executável; esses ficam em `requirements-desktop.txt`).
6. **Confira o primeiro acesso.** A primeira abertura mostra "Preparando os dados pela
   primeira vez…" enquanto baixa o pacote. Depois confira:
   - a barra lateral mostra "Dados v… · atualizados em …" e o aviso de probabilidades experimentais;
   - **Sistema e atualizações** mostra versão, idade e última checagem dos dados;
   - botões de coleta, importação e registro aparecem desabilitados ("Somente leitura nesta versão online");
   - abra todas as páginas do menu: nenhuma deve mostrar erro.

## Como os dados chegam ao app

- No primeiro acesso (ou se o disco do app for reciclado) o app baixa `manifest.json`, depois o
  pacote, confere **tamanho e SHA-256**, extrai com validação de caminhos e troca os arquivos
  por renomeação atômica.
- Depois disso consulta o Release no máximo **uma vez por hora** (comparando o SHA-256 do
  manifesto) e só baixa de novo se houver versão nova.
- Sem rede e com dados locais, continua exibindo "dados de AAAA-MM-DD". Sem rede e sem dados,
  mostra uma mensagem clara (não uma exceção) e tenta de novo na próxima abertura.
- O banco é aberto com `mode=ro`; mesmo um erro de programação não consegue gravar nele.

## Quando a atualização falha

1. *Actions → Atualizar dados publicados*: abra a execução vermelha e leia o passo que falhou.
2. Código de saída 3 do passo "Coletar e atualizar" = nenhuma fonte respondeu; a próxima
   execução (a cada 3 h) tenta de novo. Código 2 = a fonte ainda não publicou todos os jogos de
   ontem; o pacote é publicado com o que existe.
3. O app continua funcionando com a última versão publicada.

## Pontos conhecidos

- **Tamanho e memória:** o Community Cloud tem cerca de 1 GB de RAM. Os valores reais ainda
  precisam ser medidos com o `data/nba.db` de verdade (o repositório não os traz):

  ```bash
  python scripts/build_serving_bundle.py --db data/nba.db --output-dir dist/data-release
  python scripts/measure_memory.py --db data/nba.db
  ```

  Metas: ≤ 300 MiB descompactado e ≈ 100 MiB compactado. Se passar, use
  `--min-shot-season 2022-23` (descarta arremessos mais antigos) e/ou `--no-history-files`.
- **Coleta de arremessos:** `stats.nba.com` costuma recusar IPs de nuvem; o `data-refresh`
  atualiza jogos e estatísticas de jogadores (`scripts/update_daily.py`), não os arremessos.
  Arremessos novos entram quando você publica uma base completa atualizada (veja abaixo).
- **Publicar uma base completa feita no seu computador:** gere
  `python scripts/build_serving_bundle.py --db data/nba.db --output-dir dist --full-archive dist/nba-full.tar.gz`
  e envie `nba-full.tar.gz` e `.sha256` ao Release `data-latest` (`gh release upload`); a próxima
  execução do `data-refresh` parte dela.
- **Duas fontes da base (daily-picks × data-refresh):** o `daily-picks.yml` guarda a base de
  trabalho no cache do Actions e, quando o cache expira, a reconstrói pela semente
  `prediction-seed-v1` (`bootstrap_seed`). O `data-refresh` usa o Release como fonte única e cai
  na mesma semente se ele ainda não existir. O `daily-picks.yml` **não foi alterado**: os palpites
  preservados e os hashes continuam exatamente como antes.

## Fase 5 (não implementada): máquina própria gratuita

Se um dia o Community Cloud não bastar (memória ou "hibernação" por falta de acesso), a opção
prevista é uma VM do nível gratuito da Oracle Cloud rodando o mesmo app com
`NBA_DEPLOY_MODE=cloud` atrás de um proxy HTTPS. Nada disso foi feito ou testado aqui;
só vale decidir depois de medir o app real.
