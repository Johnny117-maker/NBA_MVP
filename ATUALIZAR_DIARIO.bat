@echo off
setlocal EnableExtensions
set "PYTHONUTF8=1"
cd /d "%~dp0"
rem Atualizacao diaria sem janela de pausa; usada pela tarefa agendada.
rem O resultado fica em data\atualizacao_diaria.log.
if not exist "data" mkdir "data"
if not exist ".venv\Scripts\python.exe" (
    echo [%date% %time%] Ambiente virtual nao encontrado. Execute INSTALAR_DEPENDENCIAS.bat. >> "data\atualizacao_diaria.log"
    exit /b 1
)
echo ===== %date% %time% ===== >> "data\atualizacao_diaria.log"
".venv\Scripts\python.exe" scripts\update_daily.py >> "data\atualizacao_diaria.log" 2>&1
exit /b %ERRORLEVEL%
