# cell_high_solution

A local-first Codex skill that turns one blurry image into one sharp 4× PNG through the fastest suitable ComfyUI route.

It uses no cloud inference, image captioning, web search, or multi-seed comparison during ordinary processing. The default `auto` mode favors structural fidelity and produces exactly one result.

## Routes

| Mode | Pipeline | Intended use |
| --- | --- | --- |
| `auto` | Local statistics → conservative routing | Recommended default |
| `faithful` / `fast` | RealESRGAN x4 | Figures, text, transparent layers, uncertain content |
| `restore` / `balanced` | SeedVR2 3B, one step | Heavily degraded ordinary photos |
| `redraw` | FLUX.2 Klein + RealESRGAN x4 | Explicit semantic reconstruction; may invent detail |

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

Health check:

```powershell
& "$SkillRoot\scripts\run.ps1" -Check -Tier all
```

Set `COMFYUI_PORTABLE_ROOT`, `COMFYUI_ROOT`, `COMFY_HOST`, or `CELL_HIGH_SOLUTION_OUTPUT_ROOT` to override discovery and output locations.

## Design goals

- One input and one output by default.
- Hash-derived deterministic seeds for generative routes.
- A single faithful fallback instead of multi-seed retries.
- Alpha-safe preprocessing and 4× transparent PNG output.
- Compact single-line JSON for automation and low token overhead.
- No model weights, user images, credentials, or generated outputs in this repository.

Semantic restoration cannot recover unknowable ground-truth detail. Use `redraw` only when plausible reconstruction is acceptable.

## License

Apache License 2.0. Model files retain their respective upstream licenses; see the dependency manifest before redistribution or commercial use.
