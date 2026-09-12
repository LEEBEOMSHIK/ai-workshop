param(
    [Parameter(Mandatory=$true)][string]$ArtifactRoot,
    [Parameter(Mandatory=$true)][string]$BuildId,
    [Parameter(Mandatory=$true)][string]$Compiler,
    [switch]$ContractsOnly
)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../.local-data/project-agent-work/codex-os-isolation-probe'))
if ([IO.Path]::GetFullPath($ArtifactRoot).TrimEnd('\') -ne $taskRoot.TrimEnd('\')) { throw 'Artifact root must be the exact experiment directory.' }
if ($BuildId -notmatch '^[a-zA-Z0-9-]{1,64}$') { throw 'Invalid build ID.' }
$cursor = Get-Item -LiteralPath $taskRoot
while ($null -ne $cursor) {
    if ($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse root rejected.' }
    $cursor = $cursor.Parent
}
$output = Join-Path $taskRoot ('build-' + $BuildId)
if (Test-Path -LiteralPath $output) { throw 'Build directory already exists.' }
New-Item -ItemType Directory -Path $output | Out-Null
& $Compiler /nologo /warnaserror+ /target:exe /platform:anycpu ("/out:" + (Join-Path $output 'ContractTests.exe')) (Join-Path $PSScriptRoot 'Contract.cs') (Join-Path $PSScriptRoot 'SecurityContract.cs') (Join-Path $PSScriptRoot 'ContractTests.cs')
if ($LASTEXITCODE -ne 0) { throw 'Contract compilation failed.' }
if (-not $ContractsOnly) {
    & $Compiler /nologo /warnaserror+ /target:exe /platform:anycpu ("/out:" + (Join-Path $output 'Canary.exe')) (Join-Path $PSScriptRoot 'Canary.cs') (Join-Path $PSScriptRoot 'Native.cs') (Join-Path $PSScriptRoot 'Contract.cs') (Join-Path $PSScriptRoot 'SecurityContract.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Canary compilation failed.' }
    & $Compiler /nologo /warnaserror+ /target:exe /platform:anycpu ("/out:" + (Join-Path $output 'Supervisor.exe')) (Join-Path $PSScriptRoot 'Contract.cs') (Join-Path $PSScriptRoot 'Native.cs') (Join-Path $PSScriptRoot 'SecurityScope.cs') (Join-Path $PSScriptRoot 'SecurityContract.cs') (Join-Path $PSScriptRoot 'Launch.cs') (Join-Path $PSScriptRoot 'Supervisor.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Supervisor compilation failed.' }
    Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $output 'Canary.exe')
}
Write-Output $output
