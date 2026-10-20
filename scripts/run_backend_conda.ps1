[CmdletBinding()]
param(
    [string]$CondaPython = (Join-Path $env:USERPROFILE 'miniconda3\python.exe'),
    [string]$Prefix,
    [ValidateRange(1, 65535)]
    [int]$Port = 18000,
    [switch]$CheckOnly
)

# Activate only this process using Conda's supported PowerShell integration.
# Do not install packages, edit profiles, or persist environment variables.
$ErrorActionPreference = 'Stop'
$savedLocation = Get-Location
$savedEnvironment = @{}
Get-ChildItem Env: | ForEach-Object { $savedEnvironment[$_.Name] = $_.Value }
$exitCode = 1

try {
    if (-not $PSBoundParameters.ContainsKey('Prefix')) {
        $Prefix = Join-Path $PSScriptRoot '..\backend\.conda'
    }
    $CondaPython = (Resolve-Path -LiteralPath $CondaPython).ProviderPath
    $Prefix = (Resolve-Path -LiteralPath $Prefix).ProviderPath
    $targetPython = Join-Path $Prefix 'python.exe'
    if (-not (Test-Path -LiteralPath $CondaPython -PathType Leaf) -or
        -not (Test-Path -LiteralPath $targetPython -PathType Leaf)) {
        throw 'Both the Conda Python and target prefix Python must exist.'
    }

    $activation = & $CondaPython -I -B -m conda shell.powershell activate $Prefix
    if ($LASTEXITCODE -ne 0) {
        throw "Conda activation generation failed (exit $LASTEXITCODE)."
    }
    if (-not $activation) {
        throw 'Conda returned no activation script.'
    }
    Invoke-Expression ($activation -join [Environment]::NewLine)
    if ($LASTEXITCODE -ne 0) {
        throw "Conda activation script failed (exit $LASTEXITCODE)."
    }
    if (-not $env:CONDA_PREFIX -or
        [IO.Path]::GetFullPath($env:CONDA_PREFIX).TrimEnd('\') -ine $Prefix.TrimEnd('\')) {
        throw 'Conda activation did not select the requested prefix.'
    }

    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    Set-Location -LiteralPath $repositoryRoot
    # Both the identity probe and app use these same non-isolated conditions.
    # A caller's PYTHONHOME must not redirect this Conda interpreter's prefix.
    [Environment]::SetEnvironmentVariable('PYTHONHOME', $null, 'Process')
    $sourceRoot = Join-Path $repositoryRoot 'backend\src'
    $env:PYTHONPATH = if ($env:PYTHONPATH) {
        $sourceRoot + [IO.Path]::PathSeparator + $env:PYTHONPATH
    } else { $sourceRoot }
    $env:PYTHONUTF8 = '1'
    $identityCheck = @'
import json, os, sys
from pathlib import Path
expected = Path(sys.argv[1]).resolve()
identity = {'executable': sys.executable, 'prefix': sys.prefix,
            'conda_prefix': os.environ.get('CONDA_PREFIX')}
if (Path(sys.prefix).resolve() != expected
        or Path(sys.executable).resolve() != expected / 'python.exe'
        or Path(identity['conda_prefix'] or '').resolve() != expected):
    raise SystemExit('Activated Python does not match the requested Conda prefix')
print(json.dumps(identity))
'@
    $identityResult = & $targetPython -B -c $identityCheck $Prefix
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Activated Python identity check failed (exit $exitCode)."
    }
    if ($CheckOnly) {
        Write-Output $identityResult
    }
    else {
        $exitCode = 1
        & $targetPython -B -m uvicorn ai_workshop.main:app `
            --loop ai_workshop.shared.asyncio_policy:create_selector_event_loop `
            --host 127.0.0.1 --port $Port
    }
    $exitCode = $LASTEXITCODE
}
catch {
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
}
finally {
    $currentEnvironment = @{}
    Get-ChildItem Env: | ForEach-Object { $currentEnvironment[$_.Name] = $_.Value }
    foreach ($entry in @(Get-ChildItem Env:)) {
        if (-not $savedEnvironment.ContainsKey($entry.Name)) {
            [Environment]::SetEnvironmentVariable($entry.Name, $null, 'Process')
        }
    }
    foreach ($name in $savedEnvironment.Keys) {
        if (-not $currentEnvironment.ContainsKey($name) -or
            $currentEnvironment[$name] -cne $savedEnvironment[$name]) {
            [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
        }
    }
    Set-Location -LiteralPath $savedLocation.Path
}
exit $exitCode
