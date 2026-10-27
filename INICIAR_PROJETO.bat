@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NBA Analytics Lab - Iniciar projeto

echo ============================================================
echo  NBA Analytics Lab - Inicializacao
echo ============================================================
echo.

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" goto :install_dependencies

"%VENV_PY%" -c "import streamlit" >nul 2>&1
if errorlevel 1 goto :install_dependencies

goto :run_app

:install_dependencies
echo O ambiente virtual ou o Streamlit nao foi encontrado.
echo Vou instalar as dependencias antes de iniciar.
echo.
set "NBA_CALLED_FROM_START=1"
call "%~dp0INSTALAR_DEPENDENCIAS.bat"
if errorlevel 1 goto :fail

if not exist "%VENV_PY%" (
    echo [ERRO] O ambiente virtual nao foi criado.
    goto :fail
)

:run_app
echo Iniciando o Streamlit...
echo Endereco do projeto: http://localhost:8501
echo Se o projeto ja estiver aberto em outra janela, encerre-o com Ctrl+C antes de iniciar novamente.
echo Para encerrar a aplicacao, pressione Ctrl+C nesta janela.
echo.
"%VENV_PY%" -m streamlit run app.py --server.port 8501
set "APP_EXIT_CODE=%ERRORLEVEL%"

if not "%APP_EXIT_CODE%"=="0" (
    echo.
    echo [AVISO] O Streamlit encerrou com codigo %APP_EXIT_CODE%.
    echo Se houve erro de dependencia, execute INSTALAR_DEPENDENCIAS.bat.
    echo Se a porta 8501 estiver em uso, encerre o servidor anterior antes de tentar novamente.
    echo Depois de atualizar arquivos Python, reinicie o servidor para recarregar os modulos.
    pause
)
exit /b %APP_EXIT_CODE%

:fail
echo.
echo [ERRO] Nao foi possivel iniciar o projeto.
echo Execute INSTALAR_DEPENDENCIAS.bat manualmente e confira a mensagem.
pause
exit /b 1
