#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('core', 'restore', 'redraw', 'all')]
    [string]$Tier = 'core',
    [string]$PortableRoot = '',
    [ValidateSet('default', 'cu126')]
    [string]$Runtime = 'default',
    [switch]$CheckOnly,
    [switch]$DeepVerify,
    [string]$HfEndpoint = 'https://huggingface.co'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$manifestPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'assets\dependencies.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json

if (-not $PortableRoot) {
    if ($env:COMFYUI_PORTABLE_ROOT) {
        $PortableRoot = $env:COMFYUI_PORTABLE_ROOT
    } elseif (Test-Path -LiteralPath 'F:\ComfyUI_windows_portable') {
        $PortableRoot = 'F:\ComfyUI_windows_portable'
    } elseif (Test-Path -LiteralPath 'C:\ComfyUI_windows_portable') {
        $PortableRoot = 'C:\ComfyUI_windows_portable'
    } else {
        $PortableRoot = Join-Path $env:LOCALAPPDATA 'cell_high_solution\ComfyUI_windows_portable'
    }
}
$PortableRoot = [IO.Path]::GetFullPath($PortableRoot)
$comfyRoot = Join-Path $PortableRoot 'ComfyUI'
$cacheRoot = Join-Path $env:LOCALAPPDATA 'cell_high_solution\downloads'
$results = [System.Collections.Generic.List[object]]::new()

function Add-Result([string]$Name, [string]$Status, [string]$Path, [string]$Url) {
    $results.Add([pscustomobject]@{ name = $Name; status = $Status; path = $Path; url = $Url })
}

function Get-ActualHash([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-Artifact([string]$Path, [Int64]$Size, [string]$Hash, [bool]$HashRequired) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -ne $Size) { return $false }
    if ($HashRequired -and (Get-ActualHash $Path) -ne $Hash.ToLowerInvariant()) { return $false }
    return $true
}

function Resolve-DownloadUrl([string]$Url) {
    if ($HfEndpoint -and $HfEndpoint.TrimEnd('/') -ne 'https://huggingface.co') {
        return $Url -replace '^https://huggingface\.co', $HfEndpoint.TrimEnd('/')
    }
    return $Url
}

function Download-Verified([string]$Url, [string]$Target, [Int64]$Size, [string]$Hash) {
    $urlToUse = Resolve-DownloadUrl $Url
    $parent = Split-Path $Target -Parent
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $part = "$Target.part"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source --location --fail --retry 8 --retry-all-errors --continue-at - --silent --show-error --output $part $urlToUse
        if ($LASTEXITCODE -ne 0) { throw "Download failed ($LASTEXITCODE): $urlToUse" }
    } else {
        Invoke-WebRequest -Uri $urlToUse -OutFile $part -UseBasicParsing
    }
    if (-not (Test-Artifact $part $Size $Hash $true)) {
        throw "Downloaded file failed size/SHA256 verification: $part"
    }
    Move-Item -LiteralPath $part -Destination $Target -Force
}

function Preserve-Invalid([string]$Path) {
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        Move-Item -LiteralPath $Path -Destination "$Path.bad-$stamp"
    }
}

function Ensure-Runtime {
    $pythonExe = Join-Path $PortableRoot 'python_embeded\python.exe'
    $mainPy = Join-Path $comfyRoot 'main.py'
    if ((Test-Path -LiteralPath $pythonExe) -and (Test-Path -LiteralPath $mainPy)) {
        Add-Result 'ComfyUI Windows Portable' 'present' $PortableRoot $manifest.runtime.source_page
        return
    }
    if ($CheckOnly) {
        Add-Result 'ComfyUI Windows Portable' 'missing' $PortableRoot $manifest.runtime.download_url
        return
    }
    if (Test-Path -LiteralPath $PortableRoot) {
        throw "PortableRoot exists but is not a valid ComfyUI portable install: $PortableRoot"
    }

    New-Item -ItemType Directory -Force -Path $cacheRoot | Out-Null
    $archive = Join-Path $cacheRoot "ComfyUI-$($manifest.runtime.version)-$Runtime.7z"
    if ($Runtime -eq 'cu126') {
        $url = [string]$manifest.runtime.cu126_download_url
        $size = [Int64]$manifest.runtime.cu126_size
        $hash = [string]$manifest.runtime.cu126_sha256
    } else {
        $url = [string]$manifest.runtime.download_url
        $size = [Int64]$manifest.runtime.size
        $hash = [string]$manifest.runtime.sha256
    }
    if (-not (Test-Artifact $archive $size $hash $DeepVerify.IsPresent)) {
        Preserve-Invalid $archive
        Download-Verified $url $archive $size $hash
    }

    $tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $extractRoot = Join-Path $tempBase ("cell_high_solution-extract-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $extractRoot | Out-Null
    try {
        $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
        $extracted = $false
        if ($tar) {
            & $tar.Source -xf $archive -C $extractRoot
            $extracted = ($LASTEXITCODE -eq 0)
        }
        if (-not $extracted) {
            $seven = $manifest.extractor_fallback
            $sevenExe = Join-Path $cacheRoot '7zr.exe'
            if (-not (Test-Artifact $sevenExe ([Int64]$seven.size) ([string]$seven.sha256) $DeepVerify.IsPresent)) {
                Preserve-Invalid $sevenExe
                Download-Verified ([string]$seven.download_url) $sevenExe ([Int64]$seven.size) ([string]$seven.sha256)
            }
            & $sevenExe x $archive "-o$extractRoot" -y | Out-Null
            if ($LASTEXITCODE -ne 0) { throw '7-Zip extraction failed' }
        }
        $payload = Join-Path $extractRoot ([string]$manifest.runtime.archive_root)
        if (-not (Test-Path -LiteralPath (Join-Path $payload 'ComfyUI\main.py'))) {
            throw "Extracted archive did not contain the expected ComfyUI root: $payload"
        }
        New-Item -ItemType Directory -Force -Path (Split-Path $PortableRoot -Parent) | Out-Null
        Move-Item -LiteralPath $payload -Destination $PortableRoot
    } finally {
        $resolvedExtract = [IO.Path]::GetFullPath($extractRoot)
        if ($resolvedExtract.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedExtract)) {
            Remove-Item -LiteralPath $resolvedExtract -Recurse -Force
        }
    }
    Add-Result 'ComfyUI Windows Portable' 'installed' $PortableRoot $url
}

function Tier-IsSelected([string]$ItemTier) {
    if ($ItemTier -eq 'core') { return $true }
    if ($Tier -eq 'all') { return $true }
    return $Tier -eq $ItemTier
}

Ensure-Runtime
foreach ($model in $manifest.models) {
    if (-not (Tier-IsSelected ([string]$model.tier))) { continue }
    $target = Join-Path $comfyRoot ([string]$model.relative_path)
    $valid = Test-Artifact $target ([Int64]$model.size) ([string]$model.sha256) $DeepVerify.IsPresent
    if ($valid) {
        Add-Result ([string]$model.name) 'present' $target ([string]$model.source_page)
        continue
    }
    if ($CheckOnly) {
        Add-Result ([string]$model.name) 'missing-or-invalid' $target ([string]$model.download_url)
        continue
    }
    Preserve-Invalid $target
    Download-Verified ([string]$model.download_url) $target ([Int64]$model.size) ([string]$model.sha256)
    Add-Result ([string]$model.name) 'installed' $target ([string]$model.source_page)
}

$missing = @($results | Where-Object { $_.status -in @('missing', 'missing-or-invalid') })
$payload = [ordered]@{
    ok = ($missing.Count -eq 0)
    tier = $Tier
    runtime = $Runtime
    portable_root = $PortableRoot
    check_only = $CheckOnly.IsPresent
    deep_verify = $DeepVerify.IsPresent
    dependencies_manifest = $manifestPath
    items = $results
}
$payload | ConvertTo-Json -Depth 6 -Compress
if ($missing.Count -gt 0) { exit 1 }
