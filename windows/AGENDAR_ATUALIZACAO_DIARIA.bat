@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title NBA Analytics Lab - Agendar atualizacao diaria
echo ============================================================
echo  Atualizacao diaria automatica dos jogos da NBA
echo ============================================================
echo.
if /i "%~1"=="remover" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\schedule_daily_update.ps1" -Remove
) else (
    echo Cria uma tarefa do Windows que atualiza a base as 07:00 e as 12:00,
    echo e tambem ao entrar no Windows. Se o computador estiver desligado no
    echo horario, a tarefa roda assim que ele ligar. Para desfazer:
    echo     AGENDAR_ATUALIZACAO_DIARIA.bat remover
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\schedule_daily_update.ps1"
)
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXIT_CODE%
