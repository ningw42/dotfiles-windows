"""Render Pi credential templates without reading secrets or changing the user env."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHEZMOI = shutil.which("chezmoi")
SECRET_LOADER = 'include "secrets.yaml.age" | decrypt | fromYaml'
TEMPLATES = {
    "readonly_Documents/PowerShell/Microsoft.PowerShell_profile.ps1.tmpl":
        '$Env:MAGPIE_API_KEY = "fixture-magpie-key"',
    ".chezmoiscripts/run_onchange_windows-env.ps1.tmpl":
        '[Environment]::SetEnvironmentVariable("MAGPIE_API_KEY", "fixture-magpie-key", "User")',
}


@unittest.skipUnless(CHEZMOI, "chezmoi is required to render Pi environment templates")
class PiEnvironmentTemplateTests(unittest.TestCase):
    def render(self, path, *, magpie_key):
        source = (REPO_ROOT / path).read_text(encoding="utf-8")
        self.assertEqual(source.count(SECRET_LOADER), 1)
        # Substitute only the secret-loading boundary. The actual template,
        # including its optional-key guard, still runs through chezmoi's engine.
        source = source.replace(SECRET_LOADER, ".fixtureSecrets")
        secrets = {
            "codex_api_key": "fixture-codex-key",
            "pi_api_key": "fixture-copilotd-key",
            "context7_api_key": "fixture-context7-key",
            "github_personal_access_token": "fixture-github-token",
        }
        if magpie_key:
            secrets["magpie_api_key"] = "fixture-magpie-key"

        with tempfile.TemporaryDirectory(prefix="pi-env-render-") as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            config = root / "config.json"
            config.write_text("{}", encoding="utf-8")
            env = {
                key: value for key, value in os.environ.items()
                if not key.upper().startswith("CHEZMOI_")
            }
            result = subprocess.run(
                [
                    CHEZMOI, "execute-template",
                    "--config", str(config), "--config-format", "json",
                    "--source", str(root), "--destination", str(home),
                    "--persistent-state", str(root / "state.boltdb"),
                    "--cache", str(root / "cache"),
                    "--override-data", json.dumps({
                        "colorscheme": "catppuccin-mocha",
                        "fixtureSecrets": secrets,
                        "chezmoi": {"os": "windows", "homeDir": "C:/Users/fixture"},
                    }),
                    "--refresh-externals=never", "--no-tty", "--no-pager",
                ],
                input=source, capture_output=True, text=True, encoding="utf-8",
                cwd=root, env=env, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_magpie_secret_is_exported_to_shell_and_persistent_user_environment(self):
        for path, statement in TEMPLATES.items():
            with self.subTest(path=path):
                rendered = self.render(path, magpie_key=True)
                self.assertIn(statement, rendered)
                self.assertEqual(rendered.count("MAGPIE_API_KEY"), 1)

    def test_missing_magpie_secret_renders_without_overwriting_external_credentials(self):
        for path in TEMPLATES:
            with self.subTest(path=path):
                rendered = self.render(path, magpie_key=False)
                self.assertNotIn("MAGPIE_API_KEY", rendered)
                self.assertNotIn("<no value>", rendered)


if __name__ == "__main__":
    unittest.main()
