param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,
    [ValidateRange(1024, 65535)]
    [int]$Port = 8501,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'

try {
    $projectPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $projectPython = Join-Path $projectPath '.venv\Scripts\python.exe'
    $appPath = Join-Path $projectPath 'app.py'
    $appArgument = '(?:"' + [regex]::Escape($appPath) + '"|' + [regex]::Escape($appPath) + '|"app\.py"|app\.py)'
    $commandPattern = '(?i)(?:^|\s)-m\s+streamlit\s+run\s+' + $appArgument + '(?=\s|$)'

    function Test-ProjectLauncher($Process) {
        return ($null -ne $Process -and
            $Process.ExecutablePath -ieq $projectPython -and
            $Process.CommandLine -match $commandPattern)
    }

    function Get-PortListeners {
        # Consultar todas as portas distingue "porta livre" de falha na consulta.
        return @(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq $Port })
    }

    $listeners = @(Get-PortListeners)
    if ($listeners.Count -eq 0) {
        Write-Host "[OK] Porta $Port livre para iniciar o projeto."
        exit 0
    }

    $listenerIds = @($listeners.OwningProcess | Sort-Object -Unique)
    if ($listenerIds.Count -ne 1) {
        throw "A porta $Port tem mais de um processo. Nenhum programa foi encerrado."
    }

    $server = Get-CimInstance Win32_Process -Filter "ProcessId=$($listenerIds[0])"
    $launcher = $server
    if (-not (Test-ProjectLauncher $launcher)) {
        # No Windows, o Python da .venv pode iniciar um filho do Python global.
        # Esse filho so pertence ao projeto quando o pai tambem e confirmado.
        if ($null -eq $server -or $server.CommandLine -notmatch $commandPattern) {
            throw "A porta $Port esta ocupada por outro programa. Libere a porta e tente novamente."
        }
        $launcher = Get-CimInstance Win32_Process -Filter "ProcessId=$($server.ParentProcessId)"
        if (-not (Test-ProjectLauncher $launcher)) {
            throw "O processo na porta $Port nao pertence a este projeto. Nenhum programa foi encerrado."
        }
    }

    if ($CheckOnly) {
        Write-Host "[OK] Servidor deste projeto identificado na porta $Port."
        Write-Host '[OK] Ao iniciar normalmente, ele sera reiniciado para carregar as alteracoes.'
        exit 0
    }

    Write-Host 'Reiniciando o servidor deste projeto para carregar os arquivos atuais...'
    $serverIds = @($launcher.ProcessId, $server.ProcessId | Sort-Object -Unique)
    # Encerra somente os processos confirmados acima; outros projetos ficam ativos.
    Stop-Process -Id $serverIds -ErrorAction SilentlyContinue
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $listeners = @(Get-PortListeners)
        if ($listeners.Count -eq 0) {
            Write-Host "[OK] Porta $Port liberada."
            exit 0
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Nao foi possivel liberar a porta $Port. Encerre o servidor anterior com Ctrl+C e tente novamente."
} catch {
    Write-Host "[ERRO] $($_.Exception.Message)"
    exit 1
}
