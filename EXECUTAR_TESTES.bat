@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NBA Analytics Lab - Testes

echo ============================================================
echo  NBA Analytics Lab - Testes automatizados
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo O ambiente virtual nao foi encontrado. Instalando dependencias...
    call "%~dp0INSTALAR_DEPENDENCIAS.bat"
    if errorlevel 1 goto :fail
)

echo Instalando ferramentas de teste (requirements-dev.txt)...
".venv\Scripts\python.exe" -m pip install -q -r requirements-dev.txt
if errorlevel 1 goto :fail

".venv\Scripts\python.exe" -m pytest -q
set "TEST_EXIT_CODE=%ERRORLEVEL%"

echo.
if "%TEST_EXIT_CODE%"=="0" (
    echo [OK] Os testes terminaram sem falhas.
) else (
    echo [AVISO] Os testes terminaram com codigo %TEST_EXIT_CODE%.
)
pause
exit /b %TEST_EXIT_CODE%

:fail
echo.
echo [ERRO] Nao foi possivel preparar o ambiente para executar os testes.
pause
exit /b 1
