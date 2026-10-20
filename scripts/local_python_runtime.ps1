# Read-only selection of the reviewed local Windows runtime. This file never
# activates Conda, changes the environment, or starts Python.
function Assert-OrdinaryRuntimePath([string]$LiteralPath) {
    $current = [IO.Path]::GetFullPath($LiteralPath)
    while ($current) {
        $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Approved Python runtime path contains a reparse point.'
        }
        $current = [IO.Path]::GetDirectoryName($current)
    }
}

function ConvertFrom-ApprovedPythonDescriptor([byte[]]$Bytes) {
    if ($Bytes.Length -gt 4096) { throw 'Approved Python descriptor is too large.' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = [BitConverter]::ToString($sha.ComputeHash($Bytes)).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
    # Updating this identity requires another reviewed runtime transition.
    if ($digest -cne '1a233b5d84a35b7df0dba52ae1beb77023799f1aa00a18445c2eef0bbbac67c4') {
        throw 'Approved Python descriptor hash mismatch.'
    }
    $descriptor = [Text.Encoding]::UTF8.GetString($Bytes) | ConvertFrom-Json
    if ($descriptor.schema -ne 1 -or $descriptor.executable -cne 'python.exe' -or
        -not [IO.Path]::IsPathRooted($descriptor.prefix)) {
        throw 'Invalid approved Python descriptor.'
    }
    return $descriptor
}

function Resolve-ApprovedLocalPython {
    $descriptorPath = Join-Path $PSScriptRoot 'local_python_runtime.json'
    Assert-OrdinaryRuntimePath $descriptorPath
    $descriptorItem = Get-Item -LiteralPath $descriptorPath -Force -ErrorAction Stop
    if ($descriptorItem.PSIsContainer -or $descriptorItem.Length -gt 4096) {
        throw 'Invalid approved Python descriptor file.'
    }
    $descriptor = ConvertFrom-ApprovedPythonDescriptor ([IO.File]::ReadAllBytes($descriptorPath))
    if ([Environment]::GetEnvironmentVariables('Process').Contains('PYTHONHOME')) {
        throw 'PYTHONHOME must be unset for the approved runtime.'
    }
    $prefix = [IO.Path]::GetFullPath($descriptor.prefix).TrimEnd('\', '/')
    if (-not $env:CONDA_PREFIX -or
        -not [IO.Path]::IsPathRooted($env:CONDA_PREFIX) -or
        [IO.Path]::GetFullPath($env:CONDA_PREFIX).TrimEnd('\', '/') -ine $prefix) {
        throw 'Activate the approved Conda environment before running this tool.'
    }
    $metadataPath = Join-Path $prefix 'conda-meta'
    Assert-OrdinaryRuntimePath $metadataPath
    if (-not (Get-Item -LiteralPath $metadataPath -Force -ErrorAction Stop).PSIsContainer) {
        throw 'Approved runtime is not a Conda environment.'
    }
    $python = Join-Path $prefix $descriptor.executable
    Assert-OrdinaryRuntimePath $python
    $pythonItem = Get-Item -LiteralPath $python -Force -ErrorAction Stop
    if ($pythonItem.PSIsContainer -or $pythonItem.Length -gt 32MB) {
        throw 'Invalid approved Python executable.'
    }
    if ((Get-FileHash -LiteralPath $python -Algorithm SHA256 -ErrorAction Stop).Hash -ine $descriptor.sha256) {
        throw 'Approved Python executable hash mismatch.'
    }
    return $python
}
