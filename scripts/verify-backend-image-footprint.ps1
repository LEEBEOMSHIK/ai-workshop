param(
    [Parameter(Mandatory = $false)]
    [string]$Image = "ai-workshop-backend:local",

    [Parameter(Mandatory = $false)]
    [long]$MaximumImageBytes = 7GB,

    [Parameter(Mandatory = $false)]
    [long]$MaximumEmbeddedUvCacheBytes = 1MB,

    [Parameter(Mandatory = $false)]
    [ValidateSet("absent", "cpu")]
    [string]$ExpectedOcrRuntime = "absent",

    [Parameter(Mandatory = $false)]
    [ValidateSet("absent", "cpu")]
    [string]$ExpectedEmbeddingRuntime = "absent",

    [Parameter(Mandatory = $false)]
    [ValidateSet("absent", "present")]
    [string]$ExpectedDevelopmentRuntime = "absent",

    [Parameter(Mandatory = $false)]
    [ValidateSet("absent", "present")]
    [string]$ExpectedTestSources = "absent"
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

$runtimeScript = "import ai_workshop; print('runtime-ok')"
$runtimeOutput = docker run --rm --entrypoint python $Image -c $runtimeScript
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

if ($ExpectedOcrRuntime -eq "absent") {
    $ocrScript = "import importlib.util; names=('paddle', 'paddleocr', 'paddlex'); assert all(importlib.util.find_spec(name) is None for name in names); print('ocr-absent')"
} else {
    $ocrScript = "from importlib.metadata import version; assert version('paddlepaddle') == '3.2.2'; assert version('paddleocr') == '3.7.0'; assert version('paddlex') == '3.7.2'; import paddle, paddleocr, paddlex; assert not paddle.is_compiled_with_cuda(); print('ocr-cpu-ok')"
}
$ocrCheck = docker run --rm --entrypoint python $Image -c $ocrScript
if ($LASTEXITCODE -ne 0) {
    $failures.Add("OCR runtime boundary does not match $ExpectedOcrRuntime")
}
$ocrCheckValue = if ($null -eq $ocrCheck) { "" } else { $ocrCheck.Trim() }

if ($ExpectedEmbeddingRuntime -eq "absent") {
    $embeddingScript = "import importlib.util; names=('sentence_transformers', 'torch', 'triton', 'nvidia'); assert all(importlib.util.find_spec(name) is None for name in names); print('embedding-absent')"
} else {
    $embeddingScript = "from importlib.metadata import distributions, version; import torch; names={dist.metadata['Name'].lower() for dist in distributions() if dist.metadata['Name']}; assert version('torch').endswith('+cpu'); assert torch.version.cuda is None; assert 'triton' not in names; assert not any(name.startswith('nvidia-') for name in names); print('embedding-cpu-ok')"
}
$embeddingCheck = docker run --rm --entrypoint python $Image -c $embeddingScript
if ($LASTEXITCODE -ne 0) {
    $failures.Add("embedding runtime boundary does not match $ExpectedEmbeddingRuntime")
}
$embeddingCheckValue = if ($null -eq $embeddingCheck) { "" } else { $embeddingCheck.Trim() }

$developmentExpectation = if ($ExpectedDevelopmentRuntime -eq "present") { "True" } else { "False" }
$developmentScript = "from importlib.metadata import distributions; names={dist.metadata['Name'].lower() for dist in distributions() if dist.metadata['Name']}; expected=$developmentExpectation; assert ({'mypy', 'pytest', 'ruff'} <= names) is expected; print('development-' + ('present' if expected else 'absent'))"
$developmentCheck = docker run --rm --entrypoint python $Image -c $developmentScript
if ($LASTEXITCODE -ne 0) {
    $failures.Add("development runtime boundary does not match $ExpectedDevelopmentRuntime")
}
$developmentCheckValue = if ($null -eq $developmentCheck) { "" } else { $developmentCheck.Trim() }

$testSourceCommand = if ($ExpectedTestSources -eq "present") {
    "test -d /app/tests && echo tests-present"
} else {
    "test ! -e /app/tests && echo tests-absent"
}
$testSourceCheck = docker run --rm --entrypoint /bin/sh $Image -c $testSourceCommand
if ($LASTEXITCODE -ne 0) {
    $failures.Add("test source boundary does not match $ExpectedTestSources")
}
$testSourceCheckValue = if ($null -eq $testSourceCheck) { "" } else { $testSourceCheck.Trim() }

[pscustomobject]@{
    Image = $Image
    ImageBytes = $imageSize
    EmbeddedUvCacheBytes = $uvCacheSize
    RuntimeImport = $runtimeOutput.Trim()
    DataOwner = $dataOwner
    OcrRuntime = $ocrCheckValue
    EmbeddingRuntime = $embeddingCheckValue
    DevelopmentRuntime = $developmentCheckValue
    TestSources = $testSourceCheckValue
} | Format-List

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 1
}
