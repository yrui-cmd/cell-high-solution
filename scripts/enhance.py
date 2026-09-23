#!/usr/bin/env python3
"""One-command, low-overhead blurry-image to HD runner for local ComfyUI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ASSET_DIR = SKILL_DIR / "assets"
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
DEFAULT_PORTABLE_ROOT = LOCAL_APPDATA / "cell_high_solution" / "ComfyUI_windows_portable"
KNOWN_PORTABLE_ROOTS = (
    Path(r"F:\ComfyUI_windows_portable"),
    Path(r"C:\ComfyUI_windows_portable"),
    DEFAULT_PORTABLE_ROOT,
)
REDRAW_PROMPT = (
    "Perform a strict high-resolution restoration of the reference image. "
    "Treat the reference as fixed content and geometry. Preserve every visible subject, "
    "identity, object, shape, count, text, color, position, composition, perspective, "
    "proportion, edge, and background. Resolve only blur, pixelation, compression, and "
    "aliasing into crisp continuous edges and natural fine detail. Do not add, remove, "
    "replace, restyle, beautify, or rearrange anything. Preserve the exact aspect ratio "
    "and framing."
)


def emit(payload: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), file=stream)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("._")
    return cleaned[:80] or "image"


def load_redraw_prompt_file(value: str) -> tuple[str, str, str]:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > 64 * 1024:
        raise ValueError("prompt file exceeds the 64 KiB text-only limit")
    try:
        guidance = path.read_text(encoding="utf-8-sig").strip()
    except UnicodeDecodeError as error:
        raise ValueError("prompt file must be valid UTF-8 text") from error
    if not guidance:
        raise ValueError("prompt file is empty")
    prompt = (
        REDRAW_PROMPT
        + " Visual guidance only; no reference image pixels are supplied: "
        + guidance
    )
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return prompt, str(path), digest


def host_url() -> str:
    value = os.environ.get("COMFY_HOST", "127.0.0.1:8188").rstrip("/")
    return value if value.startswith(("http://", "https://")) else f"http://{value}"


def portable_root() -> Path:
    configured = os.environ.get("COMFYUI_PORTABLE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    for candidate in KNOWN_PORTABLE_ROOTS:
        if (candidate / "ComfyUI" / "main.py").is_file():
            return candidate
    return DEFAULT_PORTABLE_ROOT


def comfy_root() -> Path:
    configured = os.environ.get("COMFYUI_ROOT")
    return Path(configured).expanduser().resolve() if configured else portable_root() / "ComfyUI"


def http_json(path: str, payload: dict[str, Any] | None = None, timeout: float = 20.0) -> Any:
    url = f"{host_url()}{path}"
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def server_alive() -> bool:
    try:
        http_json("/system_stats", timeout=2.0)
        return True
    except Exception:
        return False


def ensure_server(no_autostart: bool) -> bool:
    if server_alive():
        return False
    if no_autostart:
        raise RuntimeError("ComfyUI is not reachable and --no-autostart was supplied")

    portable = portable_root()
    comfy = comfy_root()
    python_exe = portable / "python_embeded" / "python.exe"
    main_py = comfy / "main.py"
    if not python_exe.is_file() or not main_py.is_file():
        raise FileNotFoundError(
            f"ComfyUI portable runtime not found: python={python_exe}, main={main_py}"
        )

    log_dir = portable / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "cell_high_solution.log"
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    command = [
        str(python_exe),
        "-s",
        str(main_py),
        "--windows-standalone-build",
        "--disable-auto-launch",
    ]
    with log_path.open("ab") as log_handle:
        subprocess.Popen(
            command,
            cwd=str(portable),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )

    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        if server_alive():
            return True
        time.sleep(0.75)
    raise TimeoutError(f"ComfyUI did not become ready; inspect {log_path}")


def model_choices(node_name: str, field: str) -> list[str]:
    try:
        info = http_json(f"/object_info/{node_name}")
        spec = info[node_name]["input"]["required"][field]
        if not isinstance(spec, list) or not spec:
            return []
        if isinstance(spec[0], list):
            return [str(item) for item in spec[0]]
        if len(spec) > 1 and isinstance(spec[1], dict):
            values = spec[1].get("options", [])
            return [str(item) for item in values] if isinstance(values, list) else []
        return []
    except Exception:
        return []


def health_report(tier: str = "all") -> dict[str, Any]:
    system = http_json("/system_stats")
    upscale = model_choices("UpscaleModelLoader", "model_name")
    unets = model_choices("UNETLoader", "unet_name")
    clips = model_choices("CLIPLoader", "clip_name")
    vaes = model_choices("VAELoader", "vae_name")
    available = {
        "RealESRGAN_x4plus.safetensors": "RealESRGAN_x4plus.safetensors" in upscale,
        "seedvr2_3b_int8_convrot.safetensors": "seedvr2_3b_int8_convrot.safetensors" in unets,
        "flux-2-klein-4b-fp8.safetensors": "flux-2-klein-4b-fp8.safetensors" in unets,
        "qwen_3_4b.safetensors": "qwen_3_4b.safetensors" in clips,
        "seedvr2_ema_vae_fp16.safetensors": "seedvr2_ema_vae_fp16.safetensors" in vaes,
        "flux2-vae.safetensors": "flux2-vae.safetensors" in vaes,
    }
    tier_files = {
        "core": ["RealESRGAN_x4plus.safetensors"],
        "restore": [
            "RealESRGAN_x4plus.safetensors",
            "seedvr2_3b_int8_convrot.safetensors",
            "seedvr2_ema_vae_fp16.safetensors",
        ],
        "redraw": [
            "RealESRGAN_x4plus.safetensors",
            "flux-2-klein-4b-fp8.safetensors",
            "qwen_3_4b.safetensors",
            "flux2-vae.safetensors",
        ],
        "all": list(available),
    }
    required = tier_files[tier]
    return {
        "ok": all(available[name] for name in required),
        "tier": tier,
        "required": required,
        "models": available,
        "system": system,
    }


def open_normalized(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened)
        image.load()
    if image.mode == "P" and "transparency" in image.info:
        return image.convert("RGBA")
    if "A" in image.getbands():
        return image.convert("RGBA")
    return image.convert("RGB")


def composite_rgb(image: Image.Image) -> Image.Image:
    if image.mode != "RGBA":
        return image.convert("RGB")
    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, image).convert("RGB")


def image_stats(image: Image.Image) -> dict[str, Any]:
    rgba = image.convert("RGBA")
    alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    transparent_ratio = float(np.mean(alpha < 250))
    meaningful_alpha = transparent_ratio > 0.005

    sample = composite_rgb(image)
    sample.thumbnail((512, 512), Image.Resampling.LANCZOS)
    rgb = np.asarray(sample, dtype=np.float32)
    gray = rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
    if min(gray.shape) >= 3:
        lap = (
            -4.0 * gray[1:-1, 1:-1]
            + gray[:-2, 1:-1]
            + gray[2:, 1:-1]
            + gray[1:-1, :-2]
            + gray[1:-1, 2:]
        )
        blur_score = float(np.var(lap))
        gx = np.abs(np.diff(gray, axis=1))
        gy = np.abs(np.diff(gray, axis=0))
        edge_ratio = float((np.mean(gx > 24.0) + np.mean(gy > 24.0)) / 2.0)
    else:
        blur_score = 0.0
        edge_ratio = 0.0
    near_white_ratio = float(np.mean(np.all(rgb > 245.0, axis=2)))
    colorfulness = float(np.mean(np.max(rgb, axis=2) - np.min(rgb, axis=2)))
    histogram = np.bincount(np.clip(gray, 0, 255).astype(np.uint8).ravel(), minlength=256)
    probability = histogram[histogram > 0].astype(np.float64)
    probability /= probability.sum()
    entropy = float(-np.sum(probability * np.log2(probability)))
    width, height = image.size
    return {
        "width": width,
        "height": height,
        "meaningful_alpha": meaningful_alpha,
        "transparent_ratio": round(transparent_ratio, 5),
        "near_white_ratio": round(near_white_ratio, 5),
        "colorfulness": round(colorfulness, 3),
        "edge_ratio": round(edge_ratio, 5),
        "blur_score": round(blur_score, 3),
        "entropy": round(entropy, 3),
    }


def choose_auto(stats: dict[str, Any]) -> tuple[str, str]:
    if stats["meaningful_alpha"]:
        return "faithful", "transparent asset: preserve geometry and alpha"
    likely_graphic = (
        stats["near_white_ratio"] > 0.20
        or stats["entropy"] < 5.2
        or (stats["colorfulness"] < 16.0 and stats["edge_ratio"] > 0.035)
    )
    if likely_graphic:
        return "faithful", "figure/graphic-like statistics: conservative upscale"
    min_side = min(stats["width"], stats["height"])
    high_confidence_photo = (
        stats["near_white_ratio"] < 0.12
        and stats["entropy"] > 6.1
        and stats["colorfulness"] > 18.0
        and stats["edge_ratio"] < 0.18
    )
    severe_degradation = stats["blur_score"] < 105.0 or min_side < 384
    if high_confidence_photo and severe_degradation:
        return "restore", "high-confidence degraded photo: one-step restoration"
    return "faithful", "uncertain or mildly degraded content: conservative upscale"


def clean_transparent_rgb(image: Image.Image) -> Image.Image:
    if image.mode != "RGBA":
        return image.convert("RGB")
    array = np.array(image, dtype=np.uint8)
    array[array[..., 3] == 0, :3] = 255
    return Image.fromarray(array, "RGBA")


def alpha_crop_box(image: Image.Image, margin_ratio: float = 0.12) -> tuple[int, int, int, int]:
    box = image.convert("RGBA").getchannel("A").getbbox()
    if box is None:
        return (0, 0, image.width, image.height)
    left, top, right, bottom = box
    margin = max(8, int(max(right - left, bottom - top) * margin_ratio))
    return (
        max(0, left - margin), max(0, top - margin),
        min(image.width, right + margin), min(image.height, bottom + margin),
    )


def prepare_input(source: Path, image: Image.Image, mode: str, digest: str) -> tuple[str, dict[str, Any]]:
    input_dir = comfy_root() / "input" / "cell_high_solution"
    input_dir.mkdir(parents=True, exist_ok=True)
    target = input_dir / f"{safe_stem(source.stem)}_{digest[:12]}_{mode}.png"
    metadata: dict[str, Any] = {"crop_box": None, "original_size": list(image.size)}
    cleaned = clean_transparent_rgb(image)
    has_alpha = cleaned.mode == "RGBA" and np.any(np.asarray(cleaned.getchannel("A")) < 250)
    if mode == "redraw" and has_alpha:
        box = alpha_crop_box(cleaned)
        composite_rgb(cleaned.crop(box)).save(target, format="PNG", optimize=True)
        metadata.update({"crop_box": list(box), "redraw_alpha": True})
    else:
        cleaned.save(target, format="PNG", optimize=True)
        metadata["redraw_alpha"] = False
    return f"cell_high_solution/{target.name}", metadata


def load_workflow(mode: str) -> dict[str, Any]:
    filename = {"faithful": "faithful_4x.json", "restore": "restore_seedvr2_4x.json", "redraw": "redraw_flux2_4x.json"}[mode]
    return json.loads((ASSET_DIR / filename).read_text(encoding="utf-8"))


def configure_workflow(
    workflow: dict[str, Any],
    mode: str,
    input_name: str,
    prefix: str,
    seed: int,
    redraw_alpha: bool,
    redraw_prompt: str | None = None,
) -> None:
    if mode == "faithful":
        workflow["1"]["inputs"]["image"] = input_name
        workflow["4"]["inputs"]["filename_prefix"] = prefix
    elif mode == "restore":
        workflow["1"]["inputs"]["image"] = input_name
        workflow["9"]["inputs"]["filename_prefix"] = prefix
        workflow["77"]["inputs"]["seed"] = seed
    else:
        workflow["76"]["inputs"]["image"] = input_name
        workflow["9"]["inputs"]["filename_prefix"] = prefix
        workflow["139"]["inputs"]["noise_seed"] = seed
        prompt = redraw_prompt or REDRAW_PROMPT
        if redraw_alpha:
            prompt += " Keep the isolated object on a perfectly uniform pure white background."
        workflow["131"]["inputs"]["text"] = prompt


def queue_prompt(workflow: dict[str, Any]) -> str:
    response = http_json("/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())}, timeout=30.0)
    if "error" in response:
        raise RuntimeError(json.dumps(response, ensure_ascii=False))
    return str(response["prompt_id"])


def wait_for_result(prompt_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = http_json(f"/history/{prompt_id}", timeout=15.0).get(prompt_id)
        if record:
            outputs = record.get("outputs", {})
            if outputs:
                return record
            status = record.get("status", {})
            if status.get("status_str") == "error" or (status.get("completed") is True and not outputs):
                raise RuntimeError(f"ComfyUI execution failed: {status.get('messages', [])}")
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for prompt {prompt_id}")


def first_output_image(record: dict[str, Any]) -> dict[str, str]:
    for node in record.get("outputs", {}).values():
        images = node.get("images", []) if isinstance(node, dict) else []
        if images:
            item = images[0]
            return {"filename": str(item["filename"]), "subfolder": str(item.get("subfolder", "")), "type": str(item.get("type", "output"))}
    raise RuntimeError("ComfyUI returned no image output")


def download_image(descriptor: dict[str, str], destination: Path) -> None:
    query = urllib.parse.urlencode(descriptor)
    with urllib.request.urlopen(f"{host_url()}/view?{query}", timeout=120.0) as response:
        with destination.open("wb") as handle:
            shutil.copyfileobj(response, handle)


def white_to_alpha(image: Image.Image) -> Image.Image:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    distance = 255.0 - np.min(rgb, axis=2)
    alpha = np.clip((distance - 18.0) / 55.0, 0.0, 1.0)
    rgba = np.empty((*rgb.shape[:2], 4), dtype=np.uint8)
    rgba[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    rgba[..., 3] = np.round(alpha * 255.0).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def postprocess_redraw_alpha(raw_output: Path, final_output: Path, original_size: tuple[int, int], crop_box: tuple[int, int, int, int]) -> None:
    with Image.open(raw_output) as opened:
        keyed = white_to_alpha(opened)
    left, top, right, bottom = crop_box
    keyed = keyed.resize(((right - left) * 4, (bottom - top) * 4), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (original_size[0] * 4, original_size[1] * 4), (0, 0, 0, 0))
    canvas.alpha_composite(keyed, (left * 4, top * 4))
    canvas.save(final_output, format="PNG", optimize=True)


def quality_check(path: Path, original_size: tuple[int, int], require_alpha: bool, exact_size: bool) -> dict[str, Any]:
    with Image.open(path) as opened:
        opened.load()
        width, height = opened.size
        mode = opened.mode
        sample = opened.convert("RGB")
        sample.thumbnail((512, 512), Image.Resampling.LANCZOS)
        deviation = float(np.asarray(sample, dtype=np.float32).std())
        has_alpha = "A" in opened.getbands() and np.any(np.asarray(opened.convert("RGBA").getchannel("A")) < 250)
    expected = (original_size[0] * 4, original_size[1] * 4)
    if deviation < 2.0:
        raise RuntimeError("output appears blank or nearly uniform")
    if exact_size and (width, height) != expected:
        raise RuntimeError(f"unexpected output size {(width, height)}; expected {expected}")
    if not exact_size:
        source_aspect = original_size[0] / original_size[1]
        output_aspect = width / height
        aspect_error = abs(output_aspect / source_aspect - 1.0)
        if width * height < 12_000_000 or max(width, height) < 4_000:
            raise RuntimeError(
                "semantic redraw did not reach the expected post-upscale HD canvas: "
                f"{(width, height)}"
            )
        if aspect_error > 0.03:
            raise RuntimeError(
                "semantic redraw changed the source aspect ratio too much: "
                f"source={source_aspect:.5f}, output={output_aspect:.5f}"
            )
    if require_alpha and not has_alpha:
        raise RuntimeError("source transparency was not preserved")
    return {"width": width, "height": height, "mode": mode, "pixel_std": round(deviation, 3), "has_transparency": bool(has_alpha)}


def run_once(
    source: Path,
    image: Image.Image,
    mode: str,
    digest: str,
    seed: int,
    output_dir: Path,
    timeout: float,
    redraw_prompt: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    input_name, metadata = prepare_input(source, image, mode, digest)
    workflow = load_workflow(mode)
    prefix = f"cell_high_solution/{safe_stem(source.stem)}_{digest[:12]}_{mode}"
    configure_workflow(
        workflow,
        mode,
        input_name,
        prefix,
        seed,
        bool(metadata.get("redraw_alpha")),
        redraw_prompt,
    )
    prompt_id = queue_prompt(workflow)
    record = wait_for_result(prompt_id, timeout)
    descriptor = first_output_image(record)
    raw_output = output_dir / f".{safe_stem(source.stem)}_{mode}_raw.png"
    if mode == "redraw" and not metadata.get("redraw_alpha"):
        output_suffix = "redraw_upscaled"
    else:
        output_suffix = f"{mode}_4x"
    final_output = output_dir / f"{safe_stem(source.stem)}_hd_{output_suffix}.png"
    download_image(descriptor, raw_output)
    try:
        if mode == "redraw" and metadata.get("redraw_alpha"):
            postprocess_redraw_alpha(raw_output, final_output, image.size, tuple(int(v) for v in metadata["crop_box"]))
        else:
            os.replace(raw_output, final_output)
    finally:
        raw_output.unlink(missing_ok=True)
    source_has_alpha = image.mode == "RGBA" and np.any(np.asarray(image.getchannel("A")) < 250)
    qa = quality_check(final_output, image.size, bool(source_has_alpha), mode != "redraw" or bool(metadata.get("redraw_alpha")))
    qa["prompt_id"] = prompt_id
    return final_output, qa


def resolve_output_dir(source: Path, requested: str | None) -> Path:
    if requested:
        path = Path(requested).expanduser().resolve()
    else:
        root = Path(
            os.environ.get(
                "CELL_HIGH_SOLUTION_OUTPUT_ROOT",
                str(source.parent / "cell_high_solution_outputs"),
            )
        )
        path = root / f"cell_high_solution_{safe_stem(source.stem)}_{time.strftime('%Y%m%d_%H%M%S')}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_mode(requested: str, stats: dict[str, Any]) -> tuple[str, str]:
    if requested == "auto":
        return choose_auto(stats)
    aliases = {"fast": "faithful", "balanced": "restore"}
    return aliases.get(requested, requested), f"explicit mode: {requested}"


def missing_model_files(mode: str) -> list[str]:
    comfy = comfy_root()
    required = {
        "faithful": ["models/upscale_models/RealESRGAN_x4plus.safetensors"],
        "restore": [
            "models/diffusion_models/seedvr2_3b_int8_convrot.safetensors",
            "models/vae/seedvr2_ema_vae_fp16.safetensors",
        ],
        "redraw": [
            "models/diffusion_models/flux-2-klein-4b-fp8.safetensors",
            "models/text_encoders/qwen_3_4b.safetensors",
            "models/vae/flux2-vae.safetensors",
            "models/upscale_models/RealESRGAN_x4plus.safetensors",
        ],
    }[mode]
    return [relative for relative in required if not (comfy / relative).is_file()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Turn one blurry image into one locally generated HD PNG.")
    parser.add_argument("input", nargs="?", help="absolute or relative input image path")
    parser.add_argument("--mode", choices=("auto", "fast", "faithful", "balanced", "restore", "redraw"), default="auto")
    parser.add_argument("--prompt-file", help="UTF-8 visual guidance used only with explicit --mode redraw")
    parser.add_argument("--outdir", help="output directory; a unique folder is used by default")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--no-autostart", action="store_true")
    parser.add_argument("--check", action="store_true", help="check server and required models")
    parser.add_argument("--tier", choices=("core", "restore", "redraw", "all"), default="all", help="dependency tier checked by --check")
    parser.add_argument("--dry-run", action="store_true", help="route only; do not run ComfyUI")
    return parser


def parse_arguments(argv: list[str] | None = None) -> tuple[argparse.Namespace, argparse.ArgumentParser]:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.prompt_file and (args.mode != "redraw" or args.check):
        parser.error("--prompt-file requires explicit --mode redraw and cannot be used with --check")
    return args, parser


def main() -> int:
    args, parser = parse_arguments()

    if args.check:
        started = ensure_server(args.no_autostart)
        report = health_report(args.tier)
        report["server_autostarted"] = started
        emit(report)
        return 0 if report["ok"] else 1
    if not args.input:
        parser.error("input is required unless --check is used")
    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    digest = sha256_file(source)
    seed = int(digest[:14], 16) % (2**53 - 1)
    image = open_normalized(source)
    stats = image_stats(image)
    selected_mode, reason = normalize_mode(args.mode, stats)
    redraw_prompt: str | None = None
    prompt_source: str | None = None
    prompt_sha256: str | None = None
    if args.mode == "redraw":
        if args.prompt_file:
            redraw_prompt, prompt_source, prompt_sha256 = load_redraw_prompt_file(args.prompt_file)
        else:
            prompt_source = "builtin"
            prompt_sha256 = hashlib.sha256(REDRAW_PROMPT.encode("utf-8")).hexdigest()
    if args.dry_run:
        emit({
            "ok": True,
            "dry_run": True,
            "mode": selected_mode,
            "reason": reason,
            "seed": seed,
            "stats": stats,
            "prompt_source": prompt_source,
            "prompt_sha256": prompt_sha256,
            "scale_contract": (
                "semantic redraw at 1 MP, then RealESRGAN 4x; not exact source 4x"
                if selected_mode == "redraw" and not stats["meaningful_alpha"]
                else "exact source 4x"
            ),
        })
        return 0

    fallback_from: str | None = None
    missing = missing_model_files(selected_mode)
    if missing:
        if selected_mode == "faithful":
            raise FileNotFoundError(
                "missing core model; run scripts/install.ps1 -Tier core: " + ", ".join(missing)
            )
        fallback_from = selected_mode
        selected_mode = "faithful"
        reason = f"{reason}; optional model tier not installed, used faithful fallback"
        faithful_missing = missing_model_files("faithful")
        if faithful_missing:
            raise FileNotFoundError(
                "missing core model; run scripts/install.ps1 -Tier core: "
                + ", ".join(faithful_missing)
            )

    start = time.monotonic()
    server_started = ensure_server(args.no_autostart)
    output_dir = resolve_output_dir(source, args.outdir)
    try:
        output, qa = run_once(
            source,
            image,
            selected_mode,
            digest,
            seed,
            output_dir,
            args.timeout,
            redraw_prompt,
        )
    except Exception:
        if selected_mode == "faithful":
            raise
        fallback_from = selected_mode
        selected_mode = "faithful"
        reason = f"{reason}; generative route failed QA, used faithful fallback"
        output, qa = run_once(source, image, selected_mode, digest, seed, output_dir, args.timeout)
    if selected_mode == "redraw" and not stats["meaningful_alpha"]:
        scale_contract = "semantic redraw at 1 MP, then RealESRGAN 4x; not exact source 4x"
    else:
        scale_contract = "exact source 4x"
    emit({
        "ok": True, "mode": selected_mode, "reason": reason,
        "output": str(output.resolve()), "size": [qa["width"], qa["height"]],
        "scale_from_source": [
            round(qa["width"] / image.width, 4),
            round(qa["height"] / image.height, 4),
        ],
        "scale_contract": scale_contract,
        "elapsed_seconds": round(time.monotonic() - start, 2), "seed": seed,
        "server_autostarted": server_started, "fallback_from": fallback_from,
        "prompt_source": prompt_source, "prompt_sha256": prompt_sha256,
        "prompt_applied": selected_mode == "redraw",
        "metrics": stats, "qa": qa,
    })
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        emit({"ok": False, "error": "interrupted"}, stream=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        emit({"ok": False, "error": f"{type(error).__name__}: {error}"}, stream=sys.stderr)
        raise SystemExit(1)
