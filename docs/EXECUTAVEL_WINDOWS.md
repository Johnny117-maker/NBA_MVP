# Sistema para Windows

A versão desktop abre o NBA Analytics Lab em uma janela própria. Python, navegador
Qt, Streamlit, SQLite e as bibliotecas de modelos acompanham o pacote. Não é
necessário instalar dependências, configurar um servidor ou manter um terminal aberto.

## Abrir o sistema

1. Extraia **todo** o arquivo `NBAAnalyticsLab-1.6.0-Windows-x64.zip`.
2. Entre na pasta `NBAAnalyticsLab` e abra `NBAAnalyticsLab.exe`.
3. Mantenha a pasta `_internal` ao lado do executável. Ela contém o navegador e as bibliotecas.
4. Para criar o ícone de inicialização, execute `CRIAR_ATALHO.bat`. Depois abra
   **NBA Analytics Lab** na Área de Trabalho com dois cliques.

O criador do atalho usa o ícone incluído no executável e reconhece a Área de
Trabalho redirecionada para OneDrive. Ao mover a pasta do programa, execute-o
novamente para atualizar o destino do atalho.

O pacote se destina ao **Windows 10/11 de 64 bits**. Pode ser movido para outra pasta.
A primeira abertura prepara o perfil do usuário e uma base pública ampliada. A base
inicial inclui o histórico público desde 2022 disponível na compilação, incluindo 2021–22,
e o acervo de fontes. A cobertura varia conforme o conjunto e aparece na interface.

A internet é necessária para obter novos jogos, placares e estatísticas. A análise
dos dados já salvos funciona localmente. O menu **Sistema** permite recarregar a
tela, abrir a pasta dos dados, consultar logs e sair.

## Dados, atualização e funcionamento

Os dados ficam em `%LOCALAPPDATA%\NBAAnalyticsLab`:

| Pasta | Conteúdo |
|---|---|
| `data` | Bases SQLite, calendário, análises diárias e arquivos coletados |
| `models` | Modelos treinados no computador |
| `reports` | Relatórios locais |
| `.streamlit` | Configuração e chaves opcionais do próprio usuário |
| `logs` | Diagnósticos de inicialização e execução |

Para atualizar o programa, feche a janela e extraia a nova versão em uma pasta nova.
O perfil do usuário é reutilizado; a base inicial nunca substitui arquivos existentes.
Para fazer backup, feche o sistema e copie a pasta inteira do perfil.

Quem já possui a base pode usar o pacote `NBAAnalyticsLab-1.6.0-program-Windows-x64.zip`.
Ele contém somente o programa e suas bibliotecas. A partir desta versão, a tela
**Sistema e atualizações** busca a última versão estável, confere o SHA-256 e prepara
o programa numa pasta separada. Depois, atualize o atalho pela tela e reabra o sistema.
A versão anterior e os dados são preservados. Para a primeira instalação, use o ZIP completo.

O processamento e a atualização automática funcionam **enquanto o sistema estiver
aberto**. Minimizar mantém o trabalho ativo. Fechar a janela encerra o processo
interno, sem deixar um servidor externo funcionando. O programa não coleta jogos
quando o computador está desligado. Os palpites diários são gerados separadamente
pelo GitHub Actions a cada duas horas e podem ser importados em **Histórico diário**
com autenticação GitHub. Essa tarefa não depende da janela estar aberta.

O servidor interno usa uma porta livre acessível somente em `127.0.0.1`. Ele atende
à janela do aplicativo no próprio computador. O encerramento exige um token da
instância e há uma verificação do processo da janela para evitar processos órfãos.

## Trazer o histórico da versão em Python

Com as duas versões fechadas, faça backup do perfil. Para continuar com a base
anterior, copie as pastas `data`, `models` e `reports` do projeto para o perfil,
mantendo a mesma estrutura. Os bancos `nba.db`, `nba_sync.sqlite` e
`nba_analysis.sqlite` devem permanecer juntos na pasta `data` quando disponíveis.
Essa migração é pessoal: previsões, chaves e caches privados não acompanham o ZIP distribuído.

## Compilar uma nova versão

Esta etapa é somente para quem desenvolve o projeto. No Windows x64 com o ambiente
de desenvolvimento configurado, execute `GERAR_EXECUTAVEL.bat`. A saída fica em:

```text
dist/
  1.6.0/NBAAnalyticsLab/
    NBAAnalyticsLab.exe
    CRIAR_ATALHO.bat
    _internal/
    LEIA-ME.txt
    package.json
  NBAAnalyticsLab-1.6.0-Windows-x64.zip
  NBAAnalyticsLab-1.6.0-Windows-x64.sha256
  NBAAnalyticsLab-1.6.0-program-Windows-x64.zip
  NBAAnalyticsLab-1.6.0-program-Windows-x64.sha256
```

O script usa PyInstaller no modo pasta portátil. Esse formato evita extrair o
navegador e as bibliotecas pesadas a cada abertura. O pacote inclui metadados e
licenças das dependências em `_internal`. Qt é distribuído como bibliotecas dinâmicas.

O empacotamento inclui as DLLs do XGBoost, os arquivos estáticos do Streamlit e o
runtime C++ que acompanha Qt. O PATH da compilação é restrito ao Python e ao Windows
para não incorporar bibliotecas incompatíveis de ferramentas externas.

Há também o workflow manual **Gerar executável Windows** no GitHub Actions. Ele
produz um artefato para download, sem a base local que não é versionada. Os binários
ficam fora do histórico Git; o código para reconstruí-los é versionado.

Para diagnóstico técnico sem abrir a janela:

```powershell
.\NBAAnalyticsLab.exe --diagnostico "$env:TEMP\nba-diagnostico.json" --no-sync
```

O relatório verifica bibliotecas, arquivos da interface, base de dados e uma
previsão real de XGBoost. Os logs ficam no perfil do usuário. A compilação local
deve ser validada também abrindo a janela e navegando pelas telas.

Referências: [PyInstaller](https://pyinstaller.org/en/stable/operating-mode.html) e
[distribuição com Qt for Python](https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html).
