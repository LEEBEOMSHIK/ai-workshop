param(
    [Parameter(Mandatory = $false)]
    [string]$Image = "ai-workshop-backend:local",

    [Parameter(Mandatory = $false)]
    [long]$MaximumImageBytes = 7GB,

    [Parameter(Mandatory = $false)]
    [long]$MaximumEmbeddedUvCacheBytes = 1MB
)

$ErrorActionPreference = "Stop"
$failures = [System.Collections.Generic.List[string]]::new()

$imageSizeOutput = docker image inspect $Image --format "{{.Size}}"
if ($LASTEXITCODE -ne 0) {
    throw "Cannot inspect image: $Image"
}
$imageSize = [long]$imageSizeOutput.Trim()
if ($imageSize -gt $MaximumImageBytes) {
    $failures.Add("image size $imageSize exceeds $MaximumImageBytes bytes")
}

$uvCacheOutput = docker run --rm --user 0 --entrypoint /bin/sh $Image -c `
    'if [ -d /root/.cache/uv ]; then du -sb /root/.cache/uv | cut -f1; else echo 0; fi'
if ($LASTEXITCODE -ne 0) {
    throw "Cannot inspect embedded uv cache: $Image"
}
$uvCacheSize = [long]$uvCacheOutput.Trim()
if ($uvCacheSize -gt $MaximumEmbeddedUvCacheBytes) {
    $failures.Add("embedded uv cache size $uvCacheSize exceeds $MaximumEmbeddedUvCacheBytes bytes")
}

$runtimeOutput = docker run --rm --entrypoint python $Image -c `
    'import ai_workshop; print("runtime-ok")'
if ($LASTEXITCODE -ne 0 -or $runtimeOutput.Trim() -ne "runtime-ok") {
    $failures.Add("workshop user cannot import ai_workshop")
}

$dataOwnerOutput = docker run --rm --user 0 --entrypoint stat $Image -c "%u:%g" /data/objects
if ($LASTEXITCODE -ne 0) {
    throw "Cannot inspect /data/objects ownership: $Image"
}
$dataOwner = $dataOwnerOutput.Trim()
if ($dataOwner -ne "10001:10001") {
    $failures.Add("/data/objects owner is $dataOwner instead of 10001:10001")
}

[pscustomobject]@{
    Image = $Image
    ImageBytes = $imageSize
    EmbeddedUvCacheBytes = $uvCacheSize
    RuntimeImport = $runtimeOutput.Trim()
    DataOwner = $dataOwner
} | Format-List

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 1
}
