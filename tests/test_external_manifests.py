"""Offline deployment-layout regression tests using the real chezmoi renderer.

The golden deployment layout was captured from commit 0608f32. Exact URL/hash
parity passed before payloads were bound to pin IDs, so future pin updates need
no golden refresh. Only pi-distribution varies by platform; the capture checked
that all other declarations were identical across the platform matrix.
Tests need chezmoi on PATH, but never Git, network access, or the user's config.
"""

import copy
import json
import os
import shutil
import subprocess
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "external_render_baseline.json"
CHEZMOI = shutil.which("chezmoi")
THEMES = (
    "catppuccin-latte",
    "catppuccin-frappe",
    "catppuccin-macchiato",
    "catppuccin-mocha",
    "gruvbox-dark",
    "everforest-dark",
    "unknown-theme",
)
PLATFORMS = (
    ("windows", "amd64"),
    ("windows", "arm64"),
    ("linux", "amd64"),
    ("linux", "386"),
    ("darwin", "arm64"),
)
PI_MANIFEST = "dot_pi/agent/packages/.chezmoiexternal.toml"


def read_manifest_inputs(root=REPO_ROOT):
    """Return logical manifest paths/content and data, without loading config.

    Keys omit only the optional .tmpl suffix so converting a literal manifest
    to a template does not change its deployment identity. Discovery also makes
    an added or removed manifest fail the independent golden comparison.
    """
    manifests = {}
    for path in sorted(root.rglob(".chezmoiexternal.toml*")):
        relative = path.relative_to(root)
        if relative.parts[0] in {".git", "tests"} or not path.is_file():
            continue
        if path.name not in {".chezmoiexternal.toml", ".chezmoiexternal.toml.tmpl"}:
            continue
        name = relative.as_posix().removesuffix(".tmpl")
        if name in manifests:
            raise ValueError(f"Both literal and templated manifests exist: {name}")
        manifests[name] = path.read_text(encoding="utf-8")
    data = tomllib.loads((root / ".chezmoidata.toml").read_text(encoding="utf-8"))
    return manifests, data


class ManifestRenderError(RuntimeError):
    """The real renderer failed; this is never a reason to skip a test."""


def render_manifests(manifests, data, *, colorscheme, os_name, arch):
    """Render all supplied manifests in one isolated chezmoi subprocess.

    Return {logical_manifest_path: {target: native_TOML_declaration}}. Keeping
    this seam independent of fixtures also supports a one-time exact parity
    check before replacing golden URL/checksum pairs with current pin IDs.
    """
    if CHEZMOI is None:
        raise unittest.SkipTest("chezmoi is not on PATH; real external rendering tests require it")

    with TemporaryDirectory(prefix="chezmoi-external-render-") as temporary:
        root = Path(temporary)
        source = root / "source"
        templates = source / ".chezmoitemplates"
        templates.mkdir(parents=True)
        destination = root / "home"
        destination.mkdir()
        config = root / "config.json"
        config.write_text("{}", encoding="utf-8")
        (source / ".chezmoidata.json").write_text(json.dumps(data), encoding="utf-8")

        # Register the actual sources as named templates. includeTemplate uses
        # chezmoi's Go engine; toJson safely frames each rendered TOML document
        # even when it is empty or contains comments/quotes/newlines.
        fields = []
        for index, (name, content) in enumerate(sorted(manifests.items())):
            template_name = f"external-{index}"
            (templates / template_name).write_text(content, encoding="utf-8")
            fields.append(
                json.dumps(name)
                + ': {{ includeTemplate "'
                + template_name
                + '" . | toJson }}'
            )
        bundle = "{\n" + ",\n".join(fields) + "\n}"
        override = {
            "colorscheme": colorscheme,
            "chezmoi": {"os": os_name, "arch": arch},
        }
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("CHEZMOI_")}
        env.update({
            "HOME": str(destination),
            "USERPROFILE": str(destination),
            "XDG_CONFIG_HOME": str(root / "xdg-config"),
            "XDG_CACHE_HOME": str(root / "xdg-cache"),
            "XDG_DATA_HOME": str(root / "xdg-data"),
            "XDG_STATE_HOME": str(root / "xdg-state"),
            "APPDATA": str(root / "appdata"),
            "LOCALAPPDATA": str(root / "localappdata"),
        })
        result = subprocess.run(
            [
                CHEZMOI,
                "execute-template",
                "--config", str(config),
                "--config-format", "json",
                "--source", str(source),
                "--destination", str(destination),
                "--persistent-state", str(root / "state.boltdb"),
                "--cache", str(root / "cache"),
                "--override-data", json.dumps(override),
                "--refresh-externals=never",
                "--no-tty",
                "--no-pager",
            ],
            input=bundle,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=root,
            env=env,
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise ManifestRenderError(
                f"chezmoi render failed for {colorscheme}/{os_name}/{arch} "
                f"(exit {result.returncode}):\n{result.stderr}"
            )
        rendered = json.loads(result.stdout)
        return {name: tomllib.loads(content) for name, content in rendered.items()}


def expected_manifests(baseline, pins, colorscheme, os_name, arch):
    """Keep deployment choices frozen while allowing reviewed pin refreshes."""
    expected = copy.deepcopy(baseline["by_theme"][colorscheme])
    expected[PI_MANIFEST] = copy.deepcopy(baseline["pi_by_platform"][f"{os_name}/{arch}"])
    for declarations in expected.values():
        for declaration in declarations.values():
            pin = pins[declaration.pop("pin")]
            declaration["url"] = pin["url"]
            declaration["checksum"] = {"sha256": pin["sha256"]}
    return expected


@unittest.skipUnless(CHEZMOI, "chezmoi is not on PATH; real external rendering tests require it")
class ExternalManifestRenderingTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.manifests, cls.data = read_manifest_inputs()

    def test_all_manifest_declarations_match_independent_baseline(self):
        self.assertEqual(set(self.baseline["by_theme"]), set(THEMES))
        self.assertEqual(
            set(self.baseline["pi_by_platform"]),
            {f"{os_name}/{arch}" for os_name, arch in PLATFORMS},
        )
        for colorscheme in THEMES:
            self.assertEqual(len(self.baseline["by_theme"][colorscheme]), 13)
            for os_name, arch in PLATFORMS:
                with self.subTest(colorscheme=colorscheme, os=os_name, arch=arch):
                    actual = render_manifests(
                        self.manifests, self.data,
                        colorscheme=colorscheme, os_name=os_name, arch=arch,
                    )
                    expected = expected_manifests(
                        self.baseline, self.data["external_resources"]["pins"],
                        colorscheme, os_name, arch,
                    )
                    self.assertEqual(set(actual), set(expected))
                    for manifest in expected:
                        with self.subTest(manifest=manifest):
                            # Full native declarations include target names,
                            # type, URL, checksum, archive options and omissions.
                            self.assertEqual(actual[manifest], expected[manifest])
                            # JSON also distinguishes bools from numeric TOML
                            # options (Python equality treats True as 1).
                            self.assertEqual(
                                json.dumps(actual[manifest], sort_keys=True),
                                json.dumps(expected[manifest], sort_keys=True),
                            )

    def test_shared_pin_update_flows_to_bat_and_yazi_without_manifest_edits(self):
        data = copy.deepcopy(self.data)
        pins = data["external_resources"]["pins"]
        pins["catppuccin_bat_mocha"]["url"] = "https://example.test/new-theme.tmTheme"
        pins["catppuccin_bat_mocha"]["sha256"] = "1" * 64
        actual = render_manifests(
            self.manifests, data,
            colorscheme="catppuccin-mocha", os_name="windows", arch="amd64",
        )
        expected = expected_manifests(self.baseline, pins, "catppuccin-mocha", "windows", "amd64")
        self.assertEqual(actual, expected)
        self.assertEqual(
            actual["dot_config/bat/.chezmoiexternal.toml"]["themes/Catppuccin Mocha.tmTheme"]["url"],
            "https://example.test/new-theme.tmTheme",
        )
        self.assertEqual(
            actual["AppData/Roaming/yazi/config/flavors/.chezmoiexternal.toml"]["catppuccin-mocha.yazi/tmtheme.xml"]["url"],
            "https://example.test/new-theme.tmTheme",
        )

    def test_windows_unsupported_architecture_fails_explicitly(self):
        with self.assertRaisesRegex(
            ManifestRenderError,
            'pi-distribution has no release asset for architecture "386"',
        ):
            render_manifests(
                self.manifests, self.data,
                colorscheme="catppuccin-mocha", os_name="windows", arch="386",
            )

    def test_template_errors_are_failures_not_skips(self):
        with self.assertRaisesRegex(ManifestRenderError, "intentional render failure"):
            render_manifests(
                {"broken/.chezmoiexternal.toml": '{{ fail "intentional render failure" }}'},
                {}, colorscheme="unknown-theme", os_name="linux", arch="amd64",
            )

    def test_invalid_rendered_toml_is_rejected(self):
        with self.assertRaises(tomllib.TOMLDecodeError):
            render_manifests(
                {"broken/.chezmoiexternal.toml": "not valid TOML"},
                {}, colorscheme="unknown-theme", os_name="linux", arch="amd64",
            )


if __name__ == "__main__":
    unittest.main()
