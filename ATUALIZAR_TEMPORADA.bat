@echo off
setlocal EnableExtensions
set "PYTHONUTF8=1"
cd /d "%~dp0"
title NBA Analytics Lab - Atualizar temporada atual
if not exist ".venv\Scripts\python.exe" (
    call "%~dp0INSTALAR_DEPENDENCIAS.bat"
    if errorlevel 1 exit /b 1
)
echo Consultando a temporada atual e os boxscores das fontes disponiveis...
".venv\Scripts\python.exe" scripts\sync_current_season.py --once
set "SYNC_EXIT_CODE=%ERRORLEVEL%"
echo.
echo Consulte o resultado acima. O acompanhamento continuo funciona enquanto o projeto esta aberto.
pause
exit /b %SYNC_EXIT_CODE%
