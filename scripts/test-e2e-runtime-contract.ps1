[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$foundationPath = Join-Path $repositoryRoot "backend\tests\e2e\test_foundation_flow.py"
$ragPath = Join-Path $repositoryRoot "backend\tests\e2e\test_rag_search_flow.py"
$composePath = Join-Path $repositoryRoot "infrastructure\compose\compose.yaml"
$smokePath = Join-Path $repositoryRoot "scripts\smoke.ps1"

$foundation = Get-Content -LiteralPath $foundationPath -Raw
$rag = Get-Content -LiteralPath $ragPath -Raw
$compose = Get-Content -LiteralPath $composePath -Raw
$smoke = Get-Content -LiteralPath $smokePath -Raw

if ($foundation -match "TRUNCATE" -or $rag -match "TRUNCATE") {
    throw "Actual-stack fixtures must not reset shared state while runtime is live."
}
if ($foundation -notmatch "validate_prepared_e2e" -or $rag -notmatch "validate_prepared_e2e") {
    throw "Both actual-stack fixtures must enforce the prepared E2E contract."
}
if ($foundation -notmatch "await wait_for_jobs\(") {
    throw "The foundation ACL flow must await every uploaded verification job."
}

$e2eService = [regex]::Match(
    $compose,
    "(?ms)^  e2e:\r?\n(?<body>.*?)(?=^  [a-z][a-z0-9-]*:)"
)
if (-not $e2eService.Success) {
    throw "Compose e2e service block was not found."
}
if ($e2eService.Groups["body"].Value -match "depends_on:") {
    throw "Compose e2e must not auto-start API, worker, or beat dependencies."
}

$orderedMarkers = @(
    "[smoke] Resetting isolated E2E state before runtime starts",
    "[smoke] Starting the foundation API and worker phase without beat",
    "[smoke] Running foundation E2E against prepared state",
    "[smoke] Registering the committed public model catalog",
    "[smoke] Starting the RAG API and worker phase without beat",
    "[smoke] Running RAG E2E against prepared state",
    "[smoke] Starting beat only after all fixture work is complete",
    "[smoke] Resetting isolated E2E state after runtime stops"
)
$lastIndex = -1
foreach ($marker in $orderedMarkers) {
    $currentIndex = $smoke.IndexOf($marker, [StringComparison]::Ordinal)
    if ($currentIndex -le $lastIndex) {
        throw "Smoke phase marker is missing or out of order: $marker"
    }
    $lastIndex = $currentIndex
}

$finallyIndex = $smoke.IndexOf("finally {", [StringComparison]::Ordinal)
$stopIndex = $smoke.IndexOf("Stop-E2eRuntime", $finallyIndex, [StringComparison]::Ordinal)
$resetIndex = $smoke.IndexOf("Invoke-E2eReset", $finallyIndex, [StringComparison]::Ordinal)
$downIndex = $smoke.IndexOf('Invoke-Compose @("down", "--remove-orphans")', $finallyIndex, [StringComparison]::Ordinal)
if ($finallyIndex -lt 0 -or $stopIndex -le $finallyIndex -or $resetIndex -le $stopIndex) {
    throw "Finally must stop runtime before the isolated reset."
}
if ($downIndex -ge 0 -and $downIndex -le $resetIndex) {
    throw "Compose down must happen only after runtime stop and isolated reset."
}
if ($smoke -notmatch 'Where-Object \{ \$runtimeServices -contains \$_ \}') {
    throw "Runtime stop verification must ignore empty native-command output."
}

Write-Host "E2E runtime cleanup static contract passed."
