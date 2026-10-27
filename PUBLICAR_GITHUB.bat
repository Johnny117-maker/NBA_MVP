@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NBA Analytics Lab - Publicar no GitHub

echo ============================================================
echo  NBA Analytics Lab - Preparar e enviar para o GitHub
echo ============================================================
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo [ERRO] O Git nao foi encontrado.
    echo Instale o Git para Windows: https://git-scm.com/download/win
    echo Depois feche e abra esta janela e execute novamente.
    goto :fail
)

if not exist ".git" (
    echo Inicializando repositorio Git local...
    git init -b main
    if errorlevel 1 goto :git_error
)

set "CURRENT_BRANCH="
for /f "delims=" %%B in ('git symbolic-ref --quiet --short HEAD 2^>nul') do set "CURRENT_BRANCH=%%B"
if not defined CURRENT_BRANCH goto :detached_head

set "HAS_CONFLICTS="
for /f "delims=" %%F in ('git ls-files --unmerged') do set "HAS_CONFLICTS=1"
if defined HAS_CONFLICTS goto :unresolved_conflicts

echo.
echo Branch atual: "%CURRENT_BRANCH%"
echo Alteracoes encontradas:
git status --short
if errorlevel 1 goto :git_error

git diff --cached --quiet
if errorlevel 2 goto :git_error
if errorlevel 1 goto :review_staged

echo.
echo Preparando alteracoes respeitando o .gitignore...
git add -A
if errorlevel 1 goto :git_error

git diff --cached --quiet
if errorlevel 2 goto :git_error
if not errorlevel 1 goto :no_changes

:review_staged
echo.
echo Arquivos preparados para este commit:
git diff --cached --stat
if errorlevel 1 goto :git_error
echo Se voce ja preparou arquivos com git add, somente eles entram neste commit.
echo.
echo Digite a mensagem que deseja registrar neste commit.
echo Exemplo: Adiciona auditoria das previsoes de jogadores
echo.
set "COMMIT_MESSAGE_FILE=%TEMP%\nba-analytics-commit-%RANDOM%-%RANDOM%.txt"
set "NBA_COMMIT_FILE=%COMMIT_MESSAGE_FILE%"
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$message = Read-Host 'Mensagem do commit'; if ([string]::IsNullOrWhiteSpace($message)) { Write-Host '[ERRO] A mensagem do commit nao pode ficar vazia.'; exit 2 }; [System.IO.File]::WriteAllText($env:NBA_COMMIT_FILE, $message, [System.Text.UTF8Encoding]::new($false))"
if errorlevel 1 (
    if exist "%COMMIT_MESSAGE_FILE%" del "%COMMIT_MESSAGE_FILE%" >nul 2>&1
    echo.
    echo [ERRO] Nao foi possivel obter uma mensagem valida para o commit.
    goto :fail
)

git -c i18n.commitEncoding=UTF-8 commit -F "%COMMIT_MESSAGE_FILE%"
set "COMMIT_EXIT=%ERRORLEVEL%"
if exist "%COMMIT_MESSAGE_FILE%" del "%COMMIT_MESSAGE_FILE%" >nul 2>&1
if not "%COMMIT_EXIT%"=="0" (
    echo.
    echo [ERRO] O commit falhou. Confira git config user.name e user.email.
    echo Exemplo:
    echo   git config --global user.name "Seu Nome"
    echo   git config --global user.email "seu-email@example.com"
    goto :fail
)
goto :remote

:no_changes
echo Nenhuma alteracao nova para registrar; vou continuar com o envio.

:remote
set "REMOTE_URL="
for /f "delims=" %%R in ('git remote get-url origin 2^>nul') do set "REMOTE_URL=%%R"
if defined REMOTE_URL goto :push

echo.
echo Crie um repositorio vazio no GitHub antes de continuar.
echo Nao marque para criar README, .gitignore ou LICENSE automaticamente.
echo Exemplo de URL: https://github.com/SEU-USUARIO/nba-analytics-lab.git
echo.
set /p REMOTE_URL=Cole a URL HTTPS ou SSH do repositorio GitHub: 
if "%REMOTE_URL%"=="" goto :missing_remote

git remote add origin "%REMOTE_URL%"
if errorlevel 1 goto :git_error

:push
echo.
echo Repositorio remoto: %REMOTE_URL%
echo Conferindo atualizacoes no remoto...
git fetch origin
if errorlevel 1 goto :fetch_error

git show-ref --verify --quiet "refs/remotes/origin/%CURRENT_BRANCH%"
if errorlevel 2 goto :git_error
if errorlevel 1 goto :push_branch

set "REMOTE_AHEAD="
for /f "delims=" %%C in ('git rev-list --count "HEAD..refs/remotes/origin/%CURRENT_BRANCH%"') do set "REMOTE_AHEAD=%%C"
if not defined REMOTE_AHEAD goto :git_error
if not "%REMOTE_AHEAD%"=="0" goto :remote_ahead

:push_branch
echo Enviando a branch "%CURRENT_BRANCH%" para o GitHub...
git push -u origin "%CURRENT_BRANCH%"
if errorlevel 1 (
    echo.
    echo [ERRO] O envio falhou.
    echo Confira a URL do repositorio, sua permissao de escrita e a autenticacao do GitHub.
    echo Nao coloque tokens ou senhas neste arquivo BAT.
    goto :fail
)

echo.
echo [OK] Codigo enviado para o GitHub.
git log -1 --oneline
echo Confira a pagina do repositorio no navegador.
pause
exit /b 0

:missing_remote
echo [ERRO] Nenhuma URL de repositorio foi informada.
echo Execute novamente depois de criar um repositorio vazio no GitHub.
goto :fail

:detached_head
echo [ERRO] O repositorio esta em detached HEAD.
echo Selecione uma branch antes de publicar. Nenhuma branch foi renomeada.
goto :fail

:unresolved_conflicts
echo [ERRO] Existem conflitos de merge pendentes.
echo Resolva os conflitos e conclua a integracao antes de publicar.
goto :fail

:fetch_error
echo [ERRO] Nao foi possivel consultar o repositorio remoto.
echo Confira a conexao e a autenticacao do Git. Seus commits locais permanecem salvos.
goto :fail

:remote_ahead
echo [AVISO] O GitHub possui commits que ainda nao foram integrados nesta branch.
echo O envio foi interrompido. Seus commits locais permanecem salvos.
echo Integre as alteracoes remotas por merge ou rebase e execute este arquivo novamente.
echo Este script nao faz push forcado nem resolve conflitos automaticamente.
goto :fail

:git_error
echo.
echo [ERRO] Um comando Git falhou. Leia a mensagem acima e tente novamente.
goto :fail

:fail
echo.
pause
exit /b 1
