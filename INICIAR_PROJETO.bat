@echo off
setlocal EnableExtensions
set "PYTHONUTF8=1"
cd /d "%~dp0"
title NBA Analytics Lab - Iniciar projeto

echo ============================================================
echo  NBA Analytics Lab - Inicializacao
echo ============================================================
echo.

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%~dp0app.py" (
    echo [ERRO] O app.py nao foi encontrado. Execute este BAT na pasta completa do projeto.
    goto :fail
)

if not exist "%~dp0scripts\prepare_start.ps1" (
    echo [ERRO] O auxiliar scripts\prepare_start.ps1 nao foi encontrado.
    echo Atualize os arquivos do projeto antes de iniciar.
    goto :fail
)

if not exist "%VENV_PY%" goto :install_dependencies

"%VENV_PY%" -c "import streamlit as st; from packaging.version import Version; assert Version('1.66') <= Version(st.__version__) < Version('2')" >nul 2>&1
if errorlevel 1 goto :install_dependencies

goto :prepare_server

:install_dependencies
echo O ambiente virtual ou uma versao compativel do Streamlit nao foi encontrado.
echo Vou instalar as dependencias antes de iniciar.
echo.
set "NBA_CALLED_FROM_START=1"
call "%~dp0INSTALAR_DEPENDENCIAS.bat"
if errorlevel 1 goto :fail

if not exist "%VENV_PY%" (
    echo [ERRO] O ambiente virtual nao foi criado.
    goto :fail
)

:prepare_server
if /i "%~1"=="--verificar" goto :verify_start

powershell.exe -NoLogo -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0scripts\prepare_start.ps1" -ProjectRoot "%~dp0." -Port 8501
if errorlevel 1 goto :fail

:run_app
echo Iniciando o Streamlit...
echo Endereco do projeto: http://localhost:8501
echo O navegador sera aberto automaticamente quando o servidor estiver pronto.
echo Os modelos atuais sao carregados pelo aplicativo; nao e preciso retreinar para abrir.
echo Para encerrar a aplicacao, pressione Ctrl+C nesta janela.
echo.
"%VENV_PY%" -m streamlit run "%~dp0app.py" --server.port 8501 --server.headless false --server.showEmailPrompt false --browser.serverAddress localhost
set "APP_EXIT_CODE=%ERRORLEVEL%"

if not "%APP_EXIT_CODE%"=="0" (
    echo.
    echo [AVISO] O Streamlit encerrou com codigo %APP_EXIT_CODE%.
    echo Se houve erro de dependencia, execute INSTALAR_DEPENDENCIAS.bat.
    echo Se outro programa ocupar a porta 8501, libere essa porta e tente novamente.
    echo Depois de atualizar arquivos Python, reinicie o servidor para recarregar os modulos.
    pause
)
exit /b %APP_EXIT_CODE%

:verify_start
powershell.exe -NoLogo -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0scripts\prepare_start.ps1" -ProjectRoot "%~dp0." -Port 8501 -CheckOnly
exit /b %ERRORLEVEL%

:fail
echo.
echo [ERRO] Nao foi possivel iniciar o projeto.
echo Confira a mensagem acima. Se faltar algum pacote, execute INSTALAR_DEPENDENCIAS.bat.
pause
exit /b 1
