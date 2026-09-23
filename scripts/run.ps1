#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$InputPath,
    [ValidateSet('auto', 'fast', 'faithful', 'balanced', 'restore', 'redraw')]
    [string]$Mode = 'auto',
    [string]$PromptFile = '',
    [string]$OutDir = '',
    [double]$Timeout = 900,
    [switch]$NoAutostart,
    [switch]$Check,
    [ValidateSet('core', 'restore', 'redraw', 'all')]
    [string]$Tier = 'all',
    [switch]$DryRun,
    [string]$PortableRoot = ''
)

$ErrorActionPreference = 'Stop'
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

$pythonExe = Join-Path $PortableRoot 'python_embeded\python.exe'
$runner = Join-Path $PSScriptRoot 'enhance.py'
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "ComfyUI portable Python was not found at $pythonExe. Run install.ps1 first."
}
if ($Check -and $PromptFile) {
    throw 'PromptFile cannot be used with -Check.'
}

$arguments = @($runner)
if ($Check) {
    $arguments += @('--check', '--tier', $Tier)
} else {
    if (-not $InputPath) { throw 'InputPath is required unless -Check is used.' }
    if ($PromptFile -and $Mode -ne 'redraw') {
        throw 'PromptFile is only valid with explicit -Mode redraw.'
    }
    $arguments += @($InputPath, '--mode', $Mode, '--timeout', [string]$Timeout)
    if ($PromptFile) { $arguments += @('--prompt-file', $PromptFile) }
    if ($OutDir) { $arguments += @('--outdir', $OutDir) }
    if ($DryRun) { $arguments += '--dry-run' }
}
if ($NoAutostart) { $arguments += '--no-autostart' }

& $pythonExe @arguments
exit $LASTEXITCODE
