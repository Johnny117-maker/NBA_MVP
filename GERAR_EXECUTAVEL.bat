@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
echo NBA Analytics Lab - Gerar executavel Windows
echo Esta ferramenta e para compilar. O usuario do EXE nao precisa de Python.
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente de desenvolvimento ausente. Execute INSTALAR_DEPENDENCIAS.bat primeiro.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-desktop.txt
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" scripts\build_desktop.py
if errorlevel 1 goto :fail
echo.
echo Pronto. O executavel e o ZIP completo estao na pasta dist.
pause
exit /b 0
:fail
echo Falha ao gerar o executavel. Confira as mensagens acima.
pause
exit /b 1
