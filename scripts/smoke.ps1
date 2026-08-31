[CmdletBinding()]
param(
    [string]$ProjectName = "ai-workshop-smoke",
    [ValidateRange(1024, 65535)]
    [int]$ApiPort = 18000,
    [ValidateRange(1024, 65535)]
    [int]$PostgresPort = 15432,
    [ValidateRange(1024, 65535)]
    [int]$RedisPort = 16379,
    [ValidateRange(1024, 65535)]
    [int]$ElasticsearchPort = 19200,
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
    "AI_WORKSHOP_E2E_PREPARED",
    "AI_WORKSHOP_E2E_RESET",
    "AI_WORKSHOP_E2E_PROJECT",
    "API_PORT",
    "POSTGRES_PORT",
    "REDIS_PORT",
    "ELASTICSEARCH_PORT",
    "AI_WORKSHOP_ELASTICSEARCH_INDEX_PREFIX"
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

function Wait-ApiHealthy {
    $healthUri = "http://127.0.0.1:$ApiPort/api/v1/health"
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $healthUri -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                return
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "API health check did not become ready within 60 seconds."
}

function Assert-ServiceRunning {
    param([Parameter(Mandatory)][string]$Service)

    $running = & docker compose --project-name $ProjectName --file $composePath `
        ps --status running --services $Service
    $matching = @($running | Where-Object { $_ -eq $Service })
    if ($LASTEXITCODE -ne 0 -or $matching.Count -ne 1) {
        throw "$Service did not remain running."
    }
}

function Write-SmokeDiagnostics {
    Write-Host "[smoke] Project service state after failure"
    try {
        & docker compose --project-name $ProjectName --file $composePath ps --all
    }
    catch {
        Write-Warning "[smoke] Could not collect Compose service state."
    }

    Write-Host "[smoke] Bounded service logs after failure (tail 80)"
    try {
        & docker compose --project-name $ProjectName --file $composePath logs `
            --no-color --tail 80 api worker beat postgres redis elasticsearch
    }
    catch {
        Write-Warning "[smoke] Could not collect bounded Compose logs."
    }
}

function Invoke-E2eReset {
    Invoke-Compose @(
        "--profile", "test", "run", "--rm", "--no-deps", "e2e",
        "python", "-m", "tools.reset_e2e_state"
    )
}

function Stop-E2eRuntime {
    $runtimeServices = @("api", "worker", "beat")
    $stopArguments = @("stop") + $runtimeServices
    Invoke-Compose $stopArguments
    $running = & docker compose --project-name $ProjectName --file $composePath `
        ps --status running --services @runtimeServices
    $matching = @($running | Where-Object { $runtimeServices -contains $_ })
    if ($LASTEXITCODE -ne 0 -or $matching.Count -ne 0) {
        throw "API, worker, or beat remained live after stop."
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

    $secretBytes = New-Object byte[] 32
    $secretGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $secretGenerator.GetBytes($secretBytes)
    }
    finally {
        $secretGenerator.Dispose()
    }
    [Environment]::SetEnvironmentVariable(
        "AI_WORKSHOP_SECRET_KEY",
        ([BitConverter]::ToString($secretBytes)).Replace("-", ""),
        "Process"
    )
    [Environment]::SetEnvironmentVariable("AI_WORKSHOP_ENVIRONMENT", "local", "Process")
    [Environment]::SetEnvironmentVariable("AI_WORKSHOP_E2E_PREPARED", "1", "Process")
    [Environment]::SetEnvironmentVariable("AI_WORKSHOP_E2E_RESET", "1", "Process")
    [Environment]::SetEnvironmentVariable(
        "AI_WORKSHOP_E2E_PROJECT",
        $ProjectName,
        "Process"
    )
    [Environment]::SetEnvironmentVariable("API_PORT", $ApiPort.ToString(), "Process")
    [Environment]::SetEnvironmentVariable("POSTGRES_PORT", $PostgresPort.ToString(), "Process")
    [Environment]::SetEnvironmentVariable("REDIS_PORT", $RedisPort.ToString(), "Process")
    [Environment]::SetEnvironmentVariable(
        "ELASTICSEARCH_PORT",
        $ElasticsearchPort.ToString(),
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "AI_WORKSHOP_ELASTICSEARCH_INDEX_PREFIX",
        "$ProjectName-rag",
        "Process"
    )

    Write-Host "[smoke] Validating Compose configuration"
    Invoke-Compose @("config", "--quiet")

    Write-Host "[smoke] Building the shared backend image"
    Invoke-Compose @("build", "api")

    Write-Host "[smoke] Starting PostgreSQL, Redis, and Elasticsearch"
    $started = $true
    Invoke-Compose @("up", "--detach", "--wait", "postgres", "redis", "elasticsearch")

    Write-Host "[smoke] Applying migrations once"
    Invoke-Compose @("--profile", "tools", "run", "--rm", "migrate")

    Write-Host "[smoke] Preparing the pinned local E5 model cache"
    Invoke-Compose @(
        "--profile", "model-tools", "run", "--rm", "--no-deps", "--user", "0:0",
        "model-tools", "chown", "-R", "10001:10001", "/models"
    )
    Invoke-Compose @(
        "--profile", "model-tools", "run", "--rm", "--no-deps", "model-tools",
        "python", "-c",
        "from huggingface_hub import snapshot_download; snapshot_download(repo_id='intfloat/multilingual-e5-base', revision='d128750597153bb5987e10b1c3493a34e5a4502a', cache_dir='/models')"
    )

    Write-Host "[smoke] Resetting isolated E2E state before runtime starts"
    Stop-E2eRuntime
    Invoke-E2eReset

    Write-Host "[smoke] Starting the foundation API and worker phase without beat"
    Invoke-Compose @("up", "--detach", "--wait", "api", "worker")
    Wait-ApiHealthy

    Write-Host "[smoke] Running foundation E2E against prepared state"
    Invoke-Compose @(
        "--profile", "test", "run", "--rm", "--no-deps", "e2e",
        "pytest", "-p", "no:cacheprovider", "tests/e2e/test_foundation_flow.py", "-q"
    )
    Invoke-Compose @("stop", "api", "worker")

    Write-Host "[smoke] Registering the committed public model catalog"
    Invoke-Compose @("--profile", "model-tools", "run", "--rm", "model-tools")

    Write-Host "[smoke] Starting the RAG API and worker phase without beat"
    Invoke-Compose @("up", "--detach", "--wait", "api", "worker")
    Wait-ApiHealthy

    Write-Host "[smoke] Running RAG E2E against prepared state"
    Invoke-Compose @(
        "--profile", "test", "run", "--rm", "--no-deps", "e2e",
        "pytest", "-p", "no:cacheprovider", "tests/e2e/test_rag_search_flow.py", "-q"
    )
    Invoke-Compose @("stop", "api", "worker")

    Write-Host "[smoke] Starting beat only after all fixture work is complete"
    Invoke-Compose @("up", "--detach", "beat")
    Start-Sleep -Seconds 5
    Assert-ServiceRunning -Service "beat"
    Write-Host "[smoke] Passed"
}
catch {
    $exitCode = 1
    Write-Error "[smoke] Failed: $($_.Exception.Message)" -ErrorAction Continue
    Write-SmokeDiagnostics
}
finally {
    if ($started) {
        $runtimeStopped = $false
        Write-Host "[smoke] Stopping API, worker, and beat before state reset"
        try {
            Stop-E2eRuntime
            $runtimeStopped = $true
        }
        catch {
            $exitCode = 1
            Write-Error "[smoke] Runtime stop cleanup failed: $($_.Exception.Message)" `
                -ErrorAction Continue
        }
        if ($runtimeStopped) {
            Write-Host "[smoke] Resetting isolated E2E state after runtime stops"
            try {
                Invoke-E2eReset
            }
            catch {
                $exitCode = 1
                Write-Error "[smoke] State reset cleanup failed: $($_.Exception.Message)" `
                    -ErrorAction Continue
            }
        }
        else {
            Write-Error "[smoke] State reset skipped because runtime stop failed." `
                -ErrorAction Continue
        }
        if (-not $KeepServices) {
            Write-Host "[smoke] Removing isolated containers and network; retaining named volumes"
            try {
                Invoke-Compose @("down", "--remove-orphans")
            }
            catch {
                $exitCode = 1
                Write-Error "[smoke] Compose cleanup failed: $($_.Exception.Message)" `
                    -ErrorAction Continue
            }
        }
    }
    foreach ($name in $managedEnvironment) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
}

exit $exitCode
