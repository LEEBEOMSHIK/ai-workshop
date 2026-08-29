[CmdletBinding()]
param(
    [string]$ProjectName = "ai-workshop-smoke",
    [ValidateRange(1024, 65535)]
    [int]$ApiPort = 18000,
    [ValidateRange(1024, 65535)]
    [int]$PostgresPort = 15432,
    [ValidateRange(1024, 65535)]
    [int]$RedisPort = 16379,
    [switch]$KeepServices
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($ProjectName -notmatch '^ai-workshop-smoke(?:-[a-z0-9-]+)?$') {
    throw "ProjectName must start with 'ai-workshop-smoke' and contain lowercase letters, digits, or hyphens."
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$composePath = Join-Path $repositoryRoot "infrastructure\compose\compose.yaml"
$managedEnvironment = @(
    "AI_WORKSHOP_ENVIRONMENT",
    "AI_WORKSHOP_SECRET_KEY",
    "API_PORT",
    "POSTGRES_PORT",
    "REDIS_PORT"
)
$previousEnvironment = @{}
$exitCode = 0
$started = $false

foreach ($name in $managedEnvironment) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & docker compose --project-name $ProjectName --file $composePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Arguments[0])"
    }
}

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI is required."
    }
    & docker info --format "{{.ServerVersion}}" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is not running."
    }

    $secretBytes = [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    [Environment]::SetEnvironmentVariable(
        "AI_WORKSHOP_SECRET_KEY",
        [Convert]::ToHexString($secretBytes),
        "Process"
    )
    [Environment]::SetEnvironmentVariable("AI_WORKSHOP_ENVIRONMENT", "local", "Process")
    [Environment]::SetEnvironmentVariable("API_PORT", $ApiPort.ToString(), "Process")
    [Environment]::SetEnvironmentVariable("POSTGRES_PORT", $PostgresPort.ToString(), "Process")
    [Environment]::SetEnvironmentVariable("REDIS_PORT", $RedisPort.ToString(), "Process")

    Write-Host "[smoke] Validating Compose configuration"
    Invoke-Compose @("config", "--quiet")

    Write-Host "[smoke] Building the shared backend image"
    Invoke-Compose @("build", "api")

    Write-Host "[smoke] Starting PostgreSQL and Redis"
    $started = $true
    Invoke-Compose @("up", "--detach", "postgres", "redis")

    Write-Host "[smoke] Applying migrations once"
    Invoke-Compose @("--profile", "tools", "run", "--rm", "migrate")

    Write-Host "[smoke] Starting API and worker"
    Invoke-Compose @("up", "--detach", "api", "worker")

    $healthUri = "http://127.0.0.1:$ApiPort/api/v1/health"
    $healthy = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $healthUri -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $healthy) {
        throw "API health check did not become ready within 60 seconds."
    }

    Write-Host "[smoke] Running the foundation E2E flow"
    Invoke-Compose @("--profile", "test", "run", "--rm", "e2e")
    Write-Host "[smoke] Passed"
}
catch {
    $exitCode = 1
    Write-Error "[smoke] Failed: $($_.Exception.Message)"
}
finally {
    if ($started -and -not $KeepServices) {
        Write-Host "[smoke] Removing the isolated smoke project"
        try {
            Invoke-Compose @("down", "--volumes", "--remove-orphans")
        }
        catch {
            $exitCode = 1
            Write-Error "[smoke] Cleanup failed: $($_.Exception.Message)"
        }
    }
    foreach ($name in $managedEnvironment) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
}

exit $exitCode
