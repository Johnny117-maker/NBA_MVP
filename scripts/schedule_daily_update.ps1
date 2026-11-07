# Registra (ou remove) a tarefa do Windows que executa ATUALIZAR_DIARIO.bat todos os dias.
param([switch]$Remove)

$ErrorActionPreference = "Stop"
$taskName = "NBA Analytics Lab - Atualizacao diaria"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tarefa removida: $taskName"
    exit 0
}

$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $root "ATUALIZAR_DIARIO.bat"
if (-not (Test-Path $runner)) {
    throw "ATUALIZAR_DIARIO.bat nao encontrado em $root. Execute este atalho na pasta do projeto."
}

$action = New-ScheduledTaskAction -Execute $runner -WorkingDirectory $root
# Os jogos da noite (horario dos EUA) terminam de madrugada no Brasil; as fontes
# publicam com algumas horas de atraso. Duas janelas no dia e uma ao entrar no Windows.
$daily = @(
    (New-ScheduledTaskTrigger -Daily -At "07:00"),
    (New-ScheduledTaskTrigger -Daily -At "12:00")
)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$description = "Importa os jogos encerrados da NBA e confere se o dia anterior esta completo."

try {
    $triggers = $daily + @(New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers `
        -Settings $settings -Description $description -Force | Out-Null
    Write-Host "Tarefa criada: $taskName (07:00, 12:00 e ao entrar no Windows)."
}
catch {
    # Alguns computadores exigem administrador para o gatilho de logon: mantem os horarios fixos.
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $daily `
        -Settings $settings -Description $description -Force | Out-Null
    Write-Host "Tarefa criada: $taskName (07:00 e 12:00). O gatilho ao entrar no Windows exige administrador."
}
Write-Host "O resultado de cada execucao fica em data\atualizacao_diaria.log."
