[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Infrastructure', 'Migrate', 'Runtime')]
    [string]$Phase = 'Runtime',
    [switch]$WithoutFrontend
)
$ErrorActionPreference = 'Stop'
# Tool hosts may inherit two differently cased PATH entries. Normalize this
# launcher process only before Start-Process constructs its child environment.
$sandboxSearchPath = [Environment]::GetEnvironmentVariable('Path', 'Process')
[Environment]::SetEnvironmentVariable('PATH', $null, 'Process')
[Environment]::SetEnvironmentVariable('Path', $sandboxSearchPath, 'Process')
$repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$sandboxRoot = Join-Path $repository '.local-data/rag-sandbox'
$python = Join-Path $repository 'backend/.venv/Scripts/python.exe'
$script = Join-Path $PSScriptRoot 'prepare_rag_sandbox.py'
if ($Phase -ne 'Runtime') {
    & $python $script $Phase.ToLowerInvariant()
    if ($LASTEXITCODE -ne 0) { throw "Sandbox phase failed: $Phase" }
    exit 0
}
$processFile = Join-Path $sandboxRoot 'processes.json'
if (Test-Path -LiteralPath $processFile) {
    $previous = Get-Content -LiteralPath $processFile -Raw | ConvertFrom-Json
    foreach ($entry in $previous) {
        if (Get-Process -Id $entry.pid -ErrorAction SilentlyContinue) {
            throw 'Sandbox processes already recorded as live; do not start duplicate workers.'
        }
    }
}
$phases = @('api', 'worker', 'beat')
if (-not $WithoutFrontend) { $phases += 'frontend' }
$started = @()
foreach ($runtimePhase in $phases) {
    $process = Start-Process -FilePath $python -ArgumentList @('"' + $script + '"', $runtimePhase) `
        -WorkingDirectory $repository -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $sandboxRoot "logs/$runtimePhase.out.log") `
        -RedirectStandardError (Join-Path $sandboxRoot "logs/$runtimePhase.err.log")
    $started += @{ phase = $runtimePhase; pid = $process.Id; started_at = $process.StartTime.ToString('o') }
    $started | ConvertTo-Json | Set-Content -LiteralPath $processFile -Encoding utf8
    Write-Host "sandbox_process_started=$runtimePhase pid=$($process.Id)"
}
