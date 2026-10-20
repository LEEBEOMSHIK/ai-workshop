[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local_python_runtime.ps1')

function Assert-Rejected([scriptblock]$Action, [string]$Expected) {
    try { & $Action | Out-Null } catch {
        if ($_.Exception.Message -notlike "*$Expected*") { throw }
        return
    }
    throw "Expected rejection: $Expected"
}

$runtimeDescriptor = [IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'local_python_runtime.json'))
$descriptor = ConvertFrom-ApprovedPythonDescriptor $runtimeDescriptor
if ($descriptor.schema -ne 1 -or $descriptor.executable -ne 'python.exe') { throw 'Descriptor mismatch' }
$changedDescriptor = [byte[]]$runtimeDescriptor.Clone()
$changedDescriptor[0] = 32
Assert-Rejected { ConvertFrom-ApprovedPythonDescriptor $changedDescriptor } 'descriptor hash'

$savedPrefix = $env:CONDA_PREFIX
$savedPythonHome = $env:PYTHONHOME
try {
    $env:CONDA_PREFIX = $null
    $env:PYTHONHOME = $null
    Assert-Rejected { Resolve-ApprovedLocalPython } 'Activate the approved Conda environment'
    $env:CONDA_PREFIX = 'C:\unapproved-python'
    Assert-Rejected { Resolve-ApprovedLocalPython } 'Activate the approved Conda environment'
    $env:CONDA_PREFIX = $descriptor.prefix
    $env:PYTHONHOME = 'C:\another-python'
    Assert-Rejected { Resolve-ApprovedLocalPython } 'PYTHONHOME'
    $env:PYTHONHOME = ''
    if ([Environment]::GetEnvironmentVariables('Process').Contains('PYTHONHOME')) {
        Assert-Rejected { Resolve-ApprovedLocalPython } 'PYTHONHOME'
    }
    $env:PYTHONHOME = $null
    # Read-only verification of the approved executable, never launch it.
    $python = Resolve-ApprovedLocalPython
    if ($python -ne (Join-Path $descriptor.prefix 'python.exe')) { throw 'Wrong executable selected' }
    function Get-FileHash { [pscustomobject]@{ Hash = '0' * 64 } }
    Assert-Rejected { Resolve-ApprovedLocalPython } 'executable hash'
    Remove-Item Function:\Get-FileHash
    function Get-Item { [pscustomobject]@{ Attributes = [IO.FileAttributes]::ReparsePoint } }
    Assert-Rejected { Resolve-ApprovedLocalPython } 'reparse'
    Remove-Item Function:\Get-Item
} finally {
    $env:CONDA_PREFIX = $savedPrefix
    $env:PYTHONHOME = $savedPythonHome
}

foreach ($name in @('local_python_runtime.ps1', 'prepare_rag_sandbox.ps1')) {
    $tokens = $null
    $parseErrors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $name), [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
}
$sandboxSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'prepare_rag_sandbox.ps1') -Raw
if ($sandboxSource -notmatch '(?s)foreach \(\$runtimePhase in \$phases\) \{\s*\$python = Resolve-ApprovedLocalPython\s*\$process = Start-Process' -or
    $sandboxSource -notmatch '(?s)if \(\$Phase -ne ''Runtime''\) \{\s*\$python = Resolve-ApprovedLocalPython\s*& \$python') {
    throw 'Every sandbox launch must revalidate the runtime immediately before execution.'
}
Write-Host 'local_python_runtime: descriptor, activation, PYTHONHOME, executable hash, reparse and parser checks passed'
