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
    git init
    if errorlevel 1 goto :git_error
)

git branch -M main
if errorlevel 1 goto :git_error

echo.
echo Adicionando arquivos respeitando o .gitignore...
git add -A
if errorlevel 1 goto :git_error

git diff --cached --quiet
if not errorlevel 1 goto :no_changes

git commit -m "Preparar NBA Analytics Lab para GitHub"
if errorlevel 1 (
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
echo Enviando a branch main para o GitHub...
git push -u origin main
if errorlevel 1 (
    echo.
    echo [ERRO] O envio falhou.
    echo Confira a URL do repositorio, sua permissao de escrita e a autenticacao do GitHub.
    echo Nao coloque tokens ou senhas neste arquivo BAT.
    goto :fail
)

echo.
echo [OK] Codigo enviado para o GitHub.
echo Confira a pagina do repositorio no navegador.
pause
exit /b 0

:missing_remote
echo [ERRO] Nenhuma URL de repositorio foi informada.
echo Execute novamente depois de criar um repositorio vazio no GitHub.
goto :fail

:git_error
echo.
echo [ERRO] Um comando Git falhou. Leia a mensagem acima e tente novamente.
goto :fail

:fail
echo.
pause
exit /b 1
