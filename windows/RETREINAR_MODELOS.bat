@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title NBA Analytics Lab - Retreinar e auditar modelos

echo ============================================================
echo  NBA Analytics Lab - Retreino e backtest de jogadores
echo ============================================================
echo.
echo Este processo avalia previsoes fora da amostra e grava relatorios.
echo Em bases grandes, pode levar varios minutos.
echo.

if not exist ".venv\Scripts\python.exe" (
    echo O ambiente virtual nao foi encontrado. Instalando dependencias...
    call "%~dp0INSTALAR_DEPENDENCIAS.bat"
    if errorlevel 1 goto :fail
)

".venv\Scripts\python.exe" scripts\retrain_models.py
set "TRAIN_EXIT_CODE=%ERRORLEVEL%"

echo.
if "%TRAIN_EXIT_CODE%"=="0" (
    echo [OK] Retreino e avaliacao concluidos.
    echo Veja Qualidade do Modelo no app ou o arquivo:
    echo reports\player_backtest_predictions.csv
) else (
    echo [ERRO] O retreino terminou com codigo %TRAIN_EXIT_CODE%.
)
echo.
pause
exit /b %TRAIN_EXIT_CODE%

:fail
echo.
echo [ERRO] Nao foi possivel preparar o ambiente.
pause
exit /b 1
