"""Offline checks for lazygit's externally sourced theme schema compatibility."""

import copy
import hashlib
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from test_external_manifests import CHEZMOI, read_manifest_inputs, render_manifests


LAZYGIT_MANIFEST = "AppData/Local/lazygit/.chezmoiexternal.toml"
FLAVOURS = ("latte", "frappe", "macchiato", "mocha")
LEGACY_THEME = """gui:
  theme:
    activeBorderColor:
      - '#89b4fa'
      - bold
    defaultFgColor:
      - '#cdd6f4'

  authorColors:
    '*': '#b4befe'
    'Example Author': '#89b4fa'
"""
MIGRATED_THEME = """gui:
  theme:
    activeBorderColor:
      - '#89b4fa'
      - bold
    defaultFgColor:
      - '#cdd6f4'
    authorColors:
      '*': '#b4befe'
      'Example Author': '#89b4fa'
"""


@unittest.skipUnless(CHEZMOI and shutil.which("perl"), "requires chezmoi and perl on PATH")
class LazygitThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifests, data = read_manifest_inputs()
        cls.declarations = {}
        for flavour in FLAVOURS:
            rendered = render_manifests(
                {LAZYGIT_MANIFEST: manifests[LAZYGIT_MANIFEST]}, data,
                colorscheme=f"catppuccin-{flavour}", os_name="windows", arch="amd64",
            )
            cls.declarations[flavour] = rendered[LAZYGIT_MANIFEST][f"catppuccin-{flavour}-blue.yml"]

    def filter_theme(self, declaration, content):
        self.assertIn("filter", declaration, "legacy external themes need a pre-deployment schema patch")
        filter_spec = declaration["filter"]
        self.assertIsNotNone(shutil.which(filter_spec["command"]), filter_spec["command"])
        result = subprocess.run(
            [filter_spec["command"], *filter_spec["args"]],
            input=content.encode("utf-8"), capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        return result.stdout.decode("utf-8")

    def test_all_flavours_move_author_colors_under_theme(self):
        for flavour, declaration in self.declarations.items():
            with self.subTest(flavour=flavour):
                self.assertEqual(self.filter_theme(declaration, LEGACY_THEME), MIGRATED_THEME)

    def test_already_migrated_theme_is_unchanged(self):
        declaration = self.declarations["mocha"]
        self.assertEqual(self.filter_theme(declaration, MIGRATED_THEME), MIGRATED_THEME)

    def test_theme_without_author_colors_is_unchanged(self):
        theme = "gui:\n  theme:\n    activeBorderColor:\n      - '#89b4fa'\n"
        self.assertEqual(self.filter_theme(self.declarations["mocha"], theme), theme)

    def test_filter_preserves_later_sections(self):
        suffix = "\n  showIcons: true\nos:\n  edit: nvim\n  authorColors:\n    '*': '#ffffff'\n"
        declaration = self.declarations["mocha"]
        self.assertEqual(
            self.filter_theme(declaration, LEGACY_THEME + suffix), MIGRATED_THEME + suffix,
        )

    def test_filter_preserves_line_endings_and_missing_final_newline(self):
        declaration = self.declarations["mocha"]
        for newline in ("\n", "\r\n"):
            for final_newline in (True, False):
                with self.subTest(newline=repr(newline), final_newline=final_newline):
                    original, expected = LEGACY_THEME, MIGRATED_THEME
                    if not final_newline:
                        original, expected = original.rstrip("\n"), expected.rstrip("\n")
                    self.assertEqual(
                        self.filter_theme(declaration, original.replace("\n", newline)),
                        expected.replace("\n", newline),
                    )

    def test_author_colors_outside_gui_are_unchanged(self):
        theme = "os:\n  theme:\n    customColor: '#ffffff'\n\n  authorColors:\n    '*': '#000000'\n"
        self.assertEqual(self.filter_theme(self.declarations["mocha"], theme), theme)

    def test_chezmoi_verifies_original_checksum_and_renders_patched_theme(self):
        declaration = copy.deepcopy(self.declarations["mocha"])
        with TemporaryDirectory(prefix="lazygit-theme-external-") as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            destination = root / "home"
            destination.mkdir()
            upstream = root / "upstream.yml"
            upstream.write_bytes(LEGACY_THEME.encode("utf-8"))
            # chezmoi opens the portion after file:// as an OS path; Windows
            # drive letters must not gain the slash inserted by Path.as_uri().
            declaration["url"] = "file://" + upstream.as_posix()
            declaration["checksum"] = {"sha256": hashlib.sha256(upstream.read_bytes()).hexdigest()}
            (source / ".chezmoiexternal.json").write_text(
                json.dumps({"theme.yml": declaration}), encoding="utf-8",
            )
            config = root / "config.json"
            config.write_text("{}", encoding="utf-8")
            env = {key: value for key, value in os.environ.items() if not key.upper().startswith("CHEZMOI_")}
            result = subprocess.run(
                [
                    CHEZMOI, "cat", str(destination / "theme.yml"),
                    "--config", str(config), "--config-format", "json",
                    "--source", str(source), "--destination", str(destination),
                    "--persistent-state", str(root / "state.boltdb"),
                    "--cache", str(root / "cache"),
                    "--no-tty", "--no-pager",
                ],
                capture_output=True, text=True, encoding="utf-8", env=env, cwd=root, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, MIGRATED_THEME)


if __name__ == "__main__":
    unittest.main()
