# Arquitetura de publicação gratuita

Resumo da arquitetura para publicar o app online com custo zero. O texto de origem foi o pedido
das Fases 0 a 4; este arquivo registra o que foi construído e o checklist de aceitação.

## Decisões

- Repositório GitHub **público**; app no **Streamlit Community Cloud**, em modo somente leitura.
- O **GitHub Actions** (`data-refresh.yml`) coleta e publica no Release `data-latest`:
  `manifest.json` (versão, data, tamanhos, SHA-256), `nba-serving-<versão>.tar.gz` (pacote enxuto
  que o app baixa) e `nba-full.tar.gz` + `.sha256` (base completa, ponto de partida do próximo ciclo).
- O app online **nunca recebe tokens e nunca grava no GitHub**.
- Tudo é condicionado a `NBA_DEPLOY_MODE=cloud`; sem a variável o app e o executável Windows
  funcionam como antes.

```text
data-refresh (Actions) → Release data-latest → app (cloud_bootstrap, SQLite mode=ro)
```

## Componentes

| Peça | Arquivo |
|---|---|
| Modo de implantação e guarda de leitura | `src/deploy_mode.py` |
| Download, verificação e troca atômica | `src/cloud_bootstrap.py` |
| Botões/avisos/rodapé da nuvem | `src/ui/cloud.py` |
| Pacote enxuto e base completa | `src/serving_bundle.py`, `scripts/build_serving_bundle.py` |
| Publicação periódica | `.github/workflows/data-refresh.yml` |
| Medição de tamanho e memória | `scripts/measure_memory.py` |
| Passo a passo e fontes de dados | `docs/PUBLICACAO_STREAMLIT.md`, `docs/TERMOS_DE_USO_DAS_FONTES.md` |

## Checklist de aceitação

Marcado `[x]` só o que foi verificado por teste ou leitura de código; `[ ]` depende de você.

**Fase 0**
- [x] Repositório do arquivo configurável (`NBA_ARCHIVE_REPOSITORY` / secrets), com testes
- [x] `scripts/measure_memory.py` mede pacote e pico de memória por página (testado com base sintética)
- [ ] Medição com o `data/nba.db` real (o repositório não o traz) — `python scripts/measure_memory.py --db data/nba.db`

**Fase 1**
- [x] `NBA_DEPLOY_MODE` por ambiente ou Secrets; sem ela, nada muda
- [x] Na nuvem: auto-sync desligado, dados em diretório gravável, token do arquivo ignorado
- [x] SQLite aberto com `mode=ro`; sem `PRAGMA WAL` nem criação de esquema na leitura; teste confirma bytes idênticos após abrir as páginas
- [x] Bootstrap com streaming, SHA-256, manifesto, troca atômica, checagem a cada 1 h, falha de rede com/sem dados locais, mensagem clara
- [x] Testes: nuvem ligada/desligada, sem escrita, sucesso, rede fora, checksum inválido, manifesto ausente, download interrompido (sem rede real)
- [x] Botões e importações que gravam ou consultam fontes externas desabilitados com "Somente leitura nesta versão online"
- [x] `.streamlit/config.toml`: `gatherUsageStats=false`, `enableXsrfProtection=true`, tema inalterado

**Fase 2**
- [x] Análise do que as páginas leem: arremessos brutos **não** viram agregados (o Mapa de Arremessos usa as linhas)
- [x] Pacote enxuto + `manifest.json` com versão, data, tamanhos e SHA-256
- [x] Teste abre todas as 18 páginas usando só o pacote enxuto
- [x] `data-refresh.yml`: agenda, `workflow_dispatch`, concorrência, permissões mínimas, timeout, base completa no Release, issue única de falha
- [ ] Tamanho real do pacote frente às metas (≈ 300 MiB / ≈ 100 MiB) — depende da base real
- [ ] Primeira execução do workflow no GitHub (não pode ser validada offline)

**Fase 3**
- [x] `docs/PUBLICACAO_STREAMLIT.md` em PT-BR com Secrets sem tokens
- [x] `requirements.txt` sem dependências do executável (PySide6/PyInstaller ficam em `requirements-desktop.txt`)
- [ ] Publicar no share.streamlit.io e conferir o primeiro acesso

**Fase 4**
- [x] Versão e data dos dados + aviso de probabilidades experimentais na barra lateral (nuvem)
- [x] Página Sistema mostra versão, idade, última checagem e último erro
- [x] `docs/TERMOS_DE_USO_DAS_FONTES.md` (lista, sem conclusão jurídica) — [ ] revisão pelo responsável
- [x] README ("Versão online") e CHANGELOG

**Fase 5 (Oracle Cloud gratuita):** não implementada; só documentada em `docs/PUBLICACAO_STREAMLIT.md`.
