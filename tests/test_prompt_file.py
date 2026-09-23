from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "enhance.py"
SPEC = importlib.util.spec_from_file_location("cell_high_solution_enhance", MODULE_PATH)
assert SPEC and SPEC.loader
ENHANCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENHANCE)


class PromptFileTests(unittest.TestCase):
    def test_parser_accepts_prompt_file_only_for_explicit_redraw(self) -> None:
        args, _ = ENHANCE.parse_arguments(
            ["target.png", "--mode", "redraw", "--prompt-file", "guide.txt"]
        )
        self.assertEqual(args.prompt_file, "guide.txt")

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                ENHANCE.parse_arguments(
                    ["target.png", "--mode", "faithful", "--prompt-file", "guide.txt"]
                )

    def test_prompt_file_is_utf8_appended_and_hashed_without_image_input(self) -> None:
        guidance = "Crisp flat scientific diagram; preserve every object and arrow."
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.txt"
            path.write_text(guidance, encoding="utf-8")
            prompt, source, digest = ENHANCE.load_redraw_prompt_file(str(path))

        self.assertTrue(prompt.startswith(ENHANCE.REDRAW_PROMPT))
        self.assertTrue(prompt.endswith(guidance))
        self.assertEqual(source, str(path.resolve()))
        self.assertEqual(digest, hashlib.sha256(prompt.encode("utf-8")).hexdigest())

    def test_configure_workflow_preserves_default_or_uses_combined_prompt(self) -> None:
        default_workflow = ENHANCE.load_workflow("redraw")
        ENHANCE.configure_workflow(
            default_workflow, "redraw", "target.png", "out", 17, False
        )
        self.assertEqual(default_workflow["131"]["inputs"]["text"], ENHANCE.REDRAW_PROMPT)

        custom_workflow = ENHANCE.load_workflow("redraw")
        combined = ENHANCE.REDRAW_PROMPT + " Visual guidance only: clean blue arrows."
        ENHANCE.configure_workflow(
            custom_workflow, "redraw", "target.png", "out", 17, False, combined
        )
        self.assertEqual(custom_workflow["131"]["inputs"]["text"], combined)

    def test_redraw_quality_uses_hd_canvas_and_aspect_not_source_relative_3x(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            accepted = Path(directory) / "accepted.png"
            image = Image.new("RGB", (5000, 3000), "white")
            ImageDraw.Draw(image).rectangle((0, 0, 2499, 2999), fill="black")
            image.save(accepted, format="PNG")
            result = ENHANCE.quality_check(
                accepted, (2940, 1762), require_alpha=False, exact_size=False
            )
            self.assertEqual((result["width"], result["height"]), (5000, 3000))

            rejected = Path(directory) / "rejected.png"
            image.resize((3000, 1800)).save(rejected, format="PNG")
            with self.assertRaisesRegex(RuntimeError, "post-upscale HD canvas"):
                ENHANCE.quality_check(
                    rejected, (2940, 1762), require_alpha=False, exact_size=False
                )


if __name__ == "__main__":
    unittest.main()
