@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title NBA Analytics Lab - Instalar dependencias

echo ============================================================
echo  NBA Analytics Lab - Instalador de dependencias
echo ============================================================
echo.
echo Este script cria o ambiente virtual .venv e instala os pacotes
echo listados em requirements.txt. E necessario ter Python instalado
echo e acesso a internet para baixar os pacotes.
echo.

if not exist "requirements.txt" (
    echo [ERRO] O arquivo requirements.txt nao foi encontrado.
    echo Extraia todos os arquivos do ZIP e execute este BAT na pasta raiz.
    goto :fail
)

if not exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD="

    py -3.12 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3.12"

    if not defined PYTHON_CMD (
        py -3.13 --version >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=py -3.13"
    )

    if not defined PYTHON_CMD (
        py -3.11 --version >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=py -3.11"
    )

    if not defined PYTHON_CMD (
        py -3 --version >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=py -3"
    )

    if not defined PYTHON_CMD (
        python --version >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=python"
    )

    if not defined PYTHON_CMD (
        echo [ERRO] Nao encontrei Python no computador.
        echo Instale Python 3.11, 3.12 ou 3.13 e marque a opcao
        echo "Add Python to PATH" durante a instalacao.
        echo Depois execute este arquivo novamente.
        goto :fail
    )

    echo Criando ambiente virtual com: %PYTHON_CMD%
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERRO] Nao foi possivel criar o ambiente virtual.
        echo Verifique a instalacao do Python e tente novamente.
        goto :fail
    )
) else (
    echo Ambiente virtual existente encontrado: .venv
)

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] O Python do ambiente virtual nao foi encontrado.
    goto :fail
)

echo.
echo Atualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERRO] Falha ao atualizar pip. Verifique a conexao com a internet.
    goto :fail
)

echo.
echo Baixando e instalando as dependencias de requirements.txt...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERRO] A instalacao das dependencias falhou.
    echo Verifique internet, proxy/firewall e a versao do Python.
    echo Se necessario, instale Python 3.12 e execute novamente.
    goto :fail
)

echo.
echo [OK] Dependencias instaladas com sucesso.
echo Para abrir o projeto, execute INICIAR_PROJETO.bat.
if not defined NBA_CALLED_FROM_START pause
exit /b 0

:fail
echo.
echo A instalacao nao foi concluida.
if not defined NBA_CALLED_FROM_START pause
exit /b 1
