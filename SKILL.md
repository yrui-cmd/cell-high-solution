---
name: cell-high-solution
description: "Turn one blurry local image into one sharp HD PNG with the fastest suitable local ComfyUI route. Use for 去模糊、高清修复、超分辨率、高清重绘, or improving a low-resolution image; supports optional UTF-8 text-only visual guidance for explicit FLUX redraw without passing reference-image pixels."
---

# cell_high_solution

Create one high-definition PNG from one local image. Use the bundled deterministic runner; do not browse, caption the image with another model, compare multiple seeds, or generate multiple candidates unless the user explicitly asks.

## Run

Use the portable wrapper; it finds the configured or installed ComfyUI runtime:

```powershell
$SkillRoot = Join-Path $env:USERPROFILE '.codex\skills\cell-high-solution'
& "$SkillRoot\scripts\run.ps1" -InputPath '<absolute-input-image>' -Mode auto
```

The runner starts the local ComfyUI server when necessary, selects the route, waits for completion, performs basic output QA, and prints one compact JSON result. Return the `output` image to the user.

For a reference-guided semantic redraw, first describe the reference as text, save only that description in a UTF-8 file, and pass it with the target image:

```powershell
& "$SkillRoot\scripts\run.ps1" -InputPath '<target-image>' -Mode redraw -PromptFile '<absolute-utf8-prompt.txt>'
```

Never pass the reference image path to this skill. `PromptFile` is rejected outside explicit `redraw` mode. The script appends its text to the built-in preservation prompt and reports only the prompt source and SHA-256, not the full prompt.

## Choose a mode

- `auto` is the default. It uses local pixel statistics only. RGBA images, figures, diagrams, text-heavy assets, repeated structures, and uncertain cases go to the faithful route. Only high-confidence ordinary photos with severe blur or low resolution go to one-step restoration.
- `faithful` (alias `fast`) uses RealESRGAN x4. Use when the user says “最快”, “保真”, “不要改结构”, or “只放大”.
- `restore` (alias `balanced`) uses SeedVR2 3B, one diffusion step, then outputs x4. Use for a clearly photographic image with genuinely missing detail.
- `redraw` uses FLUX.2 Klein followed by RealESRGAN x4. Use only when the user explicitly asks for “高清重绘”, “语义重建”, or “补全丢失细节”. It can plausibly invent detail and is not forensic recovery. Opaque inputs are normalized to a 1 MP semantic working canvas before 4× upscaling, so the result is typically about 5K and is named `*_hd_redraw_upscaled.png`; it is not guaranteed to be exactly 4× the source dimensions.

Override the mode by changing only `--mode`; keep one result and the hash-derived seed.

## Install dependencies

Read `assets/dependencies.json` for every source URL and exact destination. For the smallest and fastest install, install only the `core` tier (ComfyUI, Pillow/NumPy bundled with portable Python, and RealESRGAN). Install the `restore` tier only for SeedVR2 and the `redraw` tier only for FLUX semantic redraw.

```powershell
$SkillRoot = Join-Path $env:USERPROFILE '.codex\skills\cell-high-solution'
& "$SkillRoot\scripts\install.ps1" -Tier core
```

Use `-Tier all` for every route. The installer skips valid existing files, downloads to temporary `.part` files, and prints source and destination paths. It never downloads during ordinary image processing.

## Operating rules

1. Give one short progress update before running.
2. Run the command once. Do not inspect or rewrite the bundled workflow unless the command reports a technical error.
3. If a generative route fails validation, the runner retries exactly once with `faithful`; do not sample another seed.
4. Preserve transparency automatically. Transparent scientific assets and semantic layers never enter a generative route under `auto`.
5. After completion, inspect only the final PNG when visual confirmation is useful. Do not spend tokens describing internal node graphs.
6. Report the chosen route, actual output dimensions and source-relative scale, elapsed time, and clickable image path. State briefly that `redraw` reconstructs plausible rather than recoverable ground-truth detail.

## Health check

Run this only for setup or troubleshooting:

```powershell
$SkillRoot = Join-Path $env:USERPROFILE '.codex\skills\cell-high-solution'
& "$SkillRoot\scripts\run.ps1" -Check -Tier all
```

Use `--dry-run '<image>'` to print the automatic route and local statistics without starting ComfyUI or generating an image.
