"""Small regression suite for offline use, reusable inputs, and README safety."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_profile as engine
import profile_cli

SVG = "{http://www.w3.org/2000/svg}"


class ProfileTests(unittest.TestCase):
    def setUp(self):
        # CI repository metadata must not change tests that specify a repository.
        self.environment = mock.patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.stats = json.loads((ROOT / "examples" / "demo-stats.json").read_text(encoding="utf-8"))

    def test_demo_is_offline_and_generates_valid_labelled_cards(self):
        tutorial_readme = ROOT / "README.md"
        before = tutorial_readme.read_bytes() if tutorial_readme.exists() else None
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "demo"
            with mock.patch.object(sys, "argv", ["generate_profile.py", "--demo", "--output-dir", str(output)]), \
                 mock.patch.object(engine, "ASSETS", output), \
                 mock.patch("urllib.request.urlopen", side_effect=AssertionError("Demo attempted a network request")), \
                 mock.patch("socket.create_connection", side_effect=AssertionError("Demo attempted a network connection")), \
                 contextlib.redirect_stdout(io.StringIO()):
                profile_cli.main(engine)

            cards = sorted(output.glob("profile-*.svg"))
            self.assertEqual(len(cards), 4)
            self.assertEqual({card.name for card in cards}, {
                "profile-dark.svg", "profile-light.svg", "profile-mobile-dark.svg", "profile-mobile-light.svg",
            })
            for card in cards:
                document = ET.parse(card).getroot()
                self.assertEqual(document.tag, SVG + "svg")
                visible_text = " ".join(document.itertext())
                self.assertIn("DEMO / SAMPLE NUMBERS", visible_text)
                self.assertIn("OFFLINE DEMO / SAMPLE DATA", visible_text)

            portrait = json.loads((output / "ascii-portrait.json").read_text(encoding="utf-8"))
            self.assertEqual((portrait["columns"], portrait["lines"]), (112, 70))
            self.assertEqual(len(portrait["rows"]), 70)
            self.assertTrue(all(len(row) == 112 for row in portrait["rows"]))
            self.assertEqual(len(portrait["colors"]), 5)
            engine.validate_portrait(portrait, {"kind": "demo", "id": "geometric-robot-v1"})
            readme = (output / "PROFILE_README.md").read_text(encoding="utf-8")
            self.assertIn("all statistics are fictional", readme)
            self.assertIn("fictional demo data", readme)
        after = tutorial_readme.read_bytes() if tutorial_readme.exists() else None
        self.assertEqual(before, after, "Generating a demo must not replace the tutorial README")

    def test_minimal_configuration_and_xml_special_characters(self):
        minimal = engine.normalize_config({"username": "octocat"})
        self.assertEqual(minimal["name"], "octocat")
        self.assertEqual(minimal["repository"], "octocat/octocat")
        self.assertIn("role", minimal)
        config = engine.normalize_config({
            "username": "octocat", "name": "A <B> & C", "role": "Research & <Build>",
        })
        svg = engine.render(config, self.stats, engine.demo_portrait(), "dark")
        document = ET.fromstring(svg)
        self.assertEqual(document.find(SVG + "title").text, "A <B> & C: terminal-style GitHub profile")
        self.assertIn("Research & <Build>", " ".join(document.itertext()))
        self.assertNotIn("<B>", svg)
        self.assertNotIn("<Build>", svg)
        self.assertIn("&lt;B&gt; &amp; C", svg)

    def test_local_image_respects_exif_orientation(self):
        image = Image.new("RGB", (120, 80), "#221727")
        draw = ImageDraw.Draw(image)
        draw.rectangle((3, 3, 45, 35), fill="white")
        draw.ellipse((65, 40, 116, 76), fill="#ff82be")
        draw.line((5, 75, 110, 8), fill="#8c4b69", width=4)
        exif = image.getexif()
        exif[274] = 6  # A phone image stored sideways, displayed 90 degrees clockwise.
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", exif=exif)
        buffer.seek(0)
        with Image.open(buffer) as local_image:
            oriented = ImageOps.exif_transpose(local_image)
            self.assertEqual(oriented.size, (80, 120))
            actual = engine.portrait_from_image(local_image)
            expected = engine.portrait_from_image(oriented)
        self.assertEqual(actual["rows"], expected["rows"])
        self.assertEqual(actual["color_rows"], expected["color_rows"])
        self.assertEqual(actual["colors"], expected["colors"])

    def test_cache_from_another_source_is_rejected(self):
        portrait = engine.demo_portrait()
        source = {"kind": "github", "username": "alice", "url": "https://avatars.githubusercontent.com/u/1"}
        portrait["source"] = source
        engine.validate_portrait(portrait, source)
        other_source = {**source, "username": "bob"}
        with self.assertRaisesRegex(ValueError, "different source"):
            engine.validate_portrait(portrait, other_source)
        damaged = copy.deepcopy(portrait)
        damaged["color_rows"][0][0] = len(damaged["colors"])
        with self.assertRaisesRegex(ValueError, "invalid palette index"):
            engine.validate_portrait(damaged, source)

    def test_root_readme_is_only_for_a_real_same_name_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "README.md"
            target.write_text("Keep this tutorial.", encoding="utf-8")
            same_name = engine.normalize_config({"username": "alice", "repository": "alice/alice"})
            tutorial = engine.normalize_config({"username": "alice", "repository": "alice/ascii-profile-lab"})
            for config, demo in [(same_name, True), (tutorial, True), (tutorial, False)]:
                with self.subTest(repository=config["repository"], demo=demo):
                    with self.assertRaisesRegex(ValueError, "reserved"):
                        profile_cli.validate_readme_target(target, config, root, demo)
            profile_cli.validate_readme_target(target, same_name, root, False)
            profile_cli.validate_readme_target(root / "PROFILE_README.md", tutorial, root, True)
            self.assertEqual(target.read_text(encoding="utf-8"), "Keep this tutorial.")


if __name__ == "__main__":
    unittest.main()
