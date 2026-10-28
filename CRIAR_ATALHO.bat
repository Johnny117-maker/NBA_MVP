@echo off
setlocal EnableExtensions
set "NBA_SHORTCUT_ROOT=%~dp0"

echo NBA Analytics Lab - Criar atalho na Area de Trabalho
powershell -NoLogo -NoProfile -Command "$ErrorActionPreference='Stop'; $exe=Join-Path $env:NBA_SHORTCUT_ROOT 'NBAAnalyticsLab.exe'; if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { $exe=Join-Path $env:NBA_SHORTCUT_ROOT 'dist\NBAAnalyticsLab\NBAAnalyticsLab.exe' }; if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Executavel ausente. Extraia o pacote completo ou execute GERAR_EXECUTAVEL.bat.' }; $exe=[IO.Path]::GetFullPath($exe); $shell=New-Object -ComObject WScript.Shell; $desktop=[string]$shell.SpecialFolders.Item('Desktop'); if (-not (Test-Path -LiteralPath $desktop -PathType Container)) { throw 'Area de Trabalho nao encontrada.' }; $path=Join-Path $desktop 'NBA Analytics Lab.lnk'; $link=$shell.CreateShortcut($path); if ((Test-Path -LiteralPath $path) -and ([IO.Path]::GetFileName($link.TargetPath) -ne 'NBAAnalyticsLab.exe')) { throw 'Ja existe outro programa com este nome. O atalho anterior foi preservado.' }; $link.TargetPath=$exe; $link.WorkingDirectory=[IO.Path]::GetDirectoryName($exe); $link.IconLocation=$exe+',0'; $link.Description='Abrir o sistema NBA Analytics Lab'; $link.WindowStyle=1; $link.Save(); $check=$shell.CreateShortcut($path); if (($check.TargetPath -ne $exe) -or ($check.WorkingDirectory -ne [IO.Path]::GetDirectoryName($exe)) -or ($check.IconLocation -ne ($exe+',0'))) { throw 'Falha ao verificar o atalho.' }; Write-Host ('Atalho criado: '+$path)"
if errorlevel 1 goto :fail
echo Pronto. Abra NBA Analytics Lab na sua Area de Trabalho.
if /I not "%~1"=="--no-pause" pause
exit /b 0

:fail
echo Nao foi possivel criar o atalho. Confira a mensagem acima.
if /I not "%~1"=="--no-pause" pause
exit /b 1
