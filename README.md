# cell_high_solution

A local-first Codex skill that turns one blurry image into one sharp HD PNG through the fastest suitable ComfyUI route. Explicit semantic redraw can also accept visual guidance from a UTF-8 text file; a reference image itself is never passed to the workflow.

It uses no cloud inference, image captioning, web search, or multi-seed comparison during ordinary processing. The default `auto` mode favors structural fidelity and produces exactly one result.

## Routes

| Mode | Pipeline | Intended use |
| --- | --- | --- |
| `auto` | Local statistics → conservative routing | Recommended default |
| `faithful` / `fast` | RealESRGAN x4 | Figures, text, transparent layers, uncertain content |
| `restore` / `balanced` | SeedVR2 3B, one step | Heavily degraded ordinary photos |
| `redraw` | FLUX.2 Klein at a 1 MP working canvas + RealESRGAN x4 | Explicit semantic reconstruction; may invent detail |

Transparent images, scientific assets, diagrams, repeated structures, and uncertain inputs never enter a generative route under `auto`.

## Install as a Codex skill

```powershell
git clone https://github.com/yrui-cmd/cell-high-solution.git `
  "$env:USERPROFILE\.codex\skills\cell-high-solution"
```

Install only the small core tier first:

```powershell
$SkillRoot = Join-Path $env:USERPROFILE '.codex\skills\cell-high-solution'
& "$SkillRoot\scripts\install.ps1" -Tier core
```

Optional dependency tiers:

```powershell
& "$SkillRoot\scripts\install.ps1" -Tier restore  # core + SeedVR2
& "$SkillRoot\scripts\install.ps1" -Tier redraw   # core + FLUX.2
& "$SkillRoot\scripts\install.ps1" -Tier all      # every route
```

The installer is resumable and idempotent. It verifies exact sizes and SHA-256 after download, preserves mismatched existing files instead of overwriting them, and uses only official ComfyUI, Comfy-Org, and Black Forest Labs sources. See [`assets/dependencies.json`](assets/dependencies.json) for pinned URLs, checksums, destinations, sizes, and licenses.

Approximate model download sizes:

- `core`: 67 MB
- `restore`: adds 3.69 GB
- `redraw`: adds 11.60 GB
- `all`: about 15.35 GB, plus the ComfyUI portable runtime when absent

No custom nodes or separate pip installation are required.

## Use

```powershell
& "$SkillRoot\scripts\run.ps1" -InputPath 'C:\images\blurry.png' -Mode auto
```

Explicit semantic redraw:

```powershell
& "$SkillRoot\scripts\run.ps1" -InputPath 'C:\images\blurry.png' -Mode redraw
```

Text-only visual guidance for redraw:

```powershell
& "$SkillRoot\scripts\run.ps1" `
  -InputPath 'C:\images\blurry.png' `
  -Mode redraw `
  -PromptFile 'C:\images\reference-description.txt'
```

`PromptFile` must contain UTF-8 text and is accepted only with explicit `-Mode redraw`. Describe the reference visually before running; do not pass its image path. The text is appended to the built-in geometry-preservation prompt. JSON output includes the prompt source and SHA-256 without echoing the full prompt.

For opaque images, redraw output is about 4× the 1 MP semantic working canvas rather than exactly 4× the original source. The output uses the honest suffix `_hd_redraw_upscaled.png`, and JSON reports both actual dimensions and source-relative scale. Faithful mode remains exact source 4×.

Health check:

```powershell
& "$SkillRoot\scripts\run.ps1" -Check -Tier all
```

Set `COMFYUI_PORTABLE_ROOT`, `COMFYUI_ROOT`, `COMFY_HOST`, or `CELL_HIGH_SOLUTION_OUTPUT_ROOT` to override discovery and output locations.

## Design goals

- One input and one output by default.
- Hash-derived deterministic seeds for generative routes.
- A single faithful fallback instead of multi-seed retries.
- Alpha-safe preprocessing; faithful output is exact source 4×.
- Honest dimensions and scale metadata for 1 MP semantic redraws.
- Text-only redraw guidance with no reference-image path or pixels in the workflow.
- Compact single-line JSON for automation and low token overhead.
- No model weights, user images, credentials, or generated outputs in this repository.

Semantic restoration cannot recover unknowable ground-truth detail. Use `redraw` only when plausible reconstruction is acceptable.

## License

Apache License 2.0. Model files retain their respective upstream licenses; see the dependency manifest before redistribution or commercial use.
