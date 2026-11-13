"""Secret-free template composition and render/diff behavior in isolated homes."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from llm_test_support import CHEZMOI, POWERSHELL, REPO_ROOT, prepare_source, render_template


@unittest.skipUnless(CHEZMOI, "chezmoi is required")
class LlmTemplateTests(unittest.TestCase):
    def test_composed_opencode_output_matches_the_pre_refactor_fixture(self):
        expected = json.loads((REPO_ROOT / "tests/fixtures/llm/opencode.json").read_text("utf-8"))
        actual = json.loads(render_template("dot_config/opencode/opencode.json.tmpl"))
        self.assertEqual(actual, expected)

    def test_composed_pi_retains_non_inference_settings(self):
        base = json.loads((REPO_ROOT / ".chezmoitemplates/llm/pi-settings-base.json").read_text("utf-8"))
        actual = json.loads(render_template("dot_pi/agent/settings.json.tmpl"))
        for key, value in base.items():
            self.assertEqual(actual[key], value, key)
        self.assertEqual(actual["defaultProvider"], "magpie-responses")
        self.assertEqual(len(actual["enabledModels"]), 11)

    def test_codex_paths_survive_toml_serialization(self):
        home = "C:/Users/O'Brien $HOME 雪 & ^ %PATH% ! (test)"
        actual = tomllib.loads(render_template("dot_codex/config.toml.tmpl", home=home))
        auth = actual["model_providers"]["copilotd"]["auth"]
        self.assertEqual(auth["args"][4], home + "/.config/llm/credentials.ps1")
        self.assertEqual(auth["args"][-1], "copilotd")

    @unittest.skipUnless(os.name == "nt" and POWERSHELL, "Windows and PowerShell 7 are required")
    def test_rendered_codex_and_pi_commands_read_the_same_protected_fixture_store(self):
        with tempfile.TemporaryDirectory(prefix="llm command roundtrip ") as temporary:
            home = Path(temporary) / "O'Brien O’Brien O‘Brien $ 雪 & ^ %PATH% ! (test)"
            helper = home / ".config/llm/credentials.ps1"
            helper.parent.mkdir(parents=True)
            shutil.copyfile(REPO_ROOT / "dot_config/llm/credentials.ps1", helper)
            env = {k: v for k, v in os.environ.items()
                   if not k.upper().endswith(("_API_KEY", "_TOKEN"))}
            value = "fixture-provider-credential"
            published = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(helper), "-Action", "Publish"],
                input=json.dumps({"schema_version": 1, "providers": {"copilotd": value, "magpie": value}}),
                capture_output=True, text=True, encoding="utf-8", env=env, timeout=20,
            )
            self.assertEqual(published.returncode, 0, published.stderr)
            self.assertEqual(published.stdout, "")
            codex = tomllib.loads(render_template("dot_codex/config.toml.tmpl", home=home.as_posix()))
            auth = codex["model_providers"]["copilotd"]["auth"]
            resolved = subprocess.run([auth["command"], *auth["args"]], capture_output=True,
                                      text=True, encoding="utf-8", env=env, timeout=20)
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            self.assertEqual(resolved.stdout, value)
            pi = json.loads(render_template("dot_pi/agent/models.json.tmpl", home=home.as_posix()))
            command = pi["providers"]["magpie-responses"]["apiKey"]
            self.assertTrue(command.startswith("!"))
            resolved = subprocess.run(command[1:], shell=True, capture_output=True,
                                      text=True, encoding="utf-8", env=env, timeout=20)
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            self.assertEqual(resolved.stdout, value)
            self.assertNotIn(value, (helper.parent / "store/snapshot.json").read_text("utf-8"))

    @unittest.skipUnless(POWERSHELL, "PowerShell 7 is required")
    def test_apply_script_paths_with_all_apostrophe_styles_parse_as_data(self):
        home = "C:/Users/O'Brien O’Brien O‘Brien"
        for path in (".chezmoiscripts/run_after_pi-subagents-agents.ps1.tmpl",
                     ".chezmoiscripts/run_before_llm-credentials.ps1.tmpl"):
            with self.subTest(path=path):
                rendered = render_template(path, home=home)
                parsed = subprocess.run(
                    [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
                     "$text=[Console]::In.ReadToEnd(); $tokens=$null; $errors=$null; "
                     "[void][Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors); "
                     "if ($errors.Count) { [Console]::Error.WriteLine(($errors.Message -join '; ')); exit 1 }"],
                    input=rendered, capture_output=True, text=True, encoding="utf-8", timeout=20,
                )
                self.assertEqual(parsed.returncode, 0, parsed.stderr)

    def test_fresh_diff_renders_every_projection_without_identity_or_secrets(self):
        with tempfile.TemporaryDirectory(prefix="llm full diff ") as temporary:
            root = Path(temporary)
            source, home = root / "source", root / "home"
            source.mkdir()
            home.mkdir()
            prepare_source(source)
            managed = [
                "dot_codex/config.toml.tmpl", "dot_pi/agent/models.json.tmpl",
                "dot_pi/agent/settings.json.tmpl", "dot_pi/workflows/model-tiers.json.tmpl",
                "dot_config/opencode/opencode.json.tmpl", "dot_config/llm/credentials.ps1",
                "readonly_Documents/PowerShell/Microsoft.PowerShell_profile.ps1.tmpl",
                ".chezmoiscripts/run_before_llm-credentials.ps1.tmpl",
                ".chezmoiscripts/run_onchange_windows-env.ps1.tmpl",
                ".chezmoiscripts/run_after_pi-subagents-agents.ps1.tmpl",
            ]
            for path in managed:
                destination = source / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO_ROOT / path, destination)
            (source / ".chezmoiignore").write_text("render_llm_config.py\n.config/llm/store/\n", encoding="utf-8")
            config = root / "config.json"
            config.write_text(json.dumps({"data": {
                "llm_python": sys.executable,
                "llm_pwsh": POWERSHELL or "C:/Program Files/PowerShell/7/pwsh.exe",
                "colorscheme": "catppuccin-mocha",
            }}), encoding="utf-8")
            command = [CHEZMOI, "--config", str(config), "--source", str(source),
                       "--destination", str(home), "--persistent-state", str(root / "state.boltdb"),
                       "--cache", str(root / "cache"), "--no-tty", "--no-pager", "--color=false",
                       "--refresh-externals=never", "diff"]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60,
                                    cwd=root, env={k: v for k, v in os.environ.items() if not k.upper().startswith("CHEZMOI_")})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("credentials.ps1", result.stdout)
            self.assertIn("magpie-responses", result.stdout)
            self.assertIn("model_providers", result.stdout)
            self.assertNotIn("diff --git a/render_llm_config.py", result.stdout)
            self.assertFalse(any(home.iterdir()), "diff must not deploy or publish")
            self.assertFalse((source / "secrets.yaml.age").exists())


if __name__ == "__main__":
    unittest.main()
