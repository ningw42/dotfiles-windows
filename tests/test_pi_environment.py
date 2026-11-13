"""Non-secret shell flags only; no real user-environment writes or secret reads."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from llm_test_support import CHEZMOI, render_template

REPO_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh")
TEMPLATES = (
    "readonly_Documents/PowerShell/Microsoft.PowerShell_profile.ps1.tmpl",
    ".chezmoiscripts/run_onchange_windows-env.ps1.tmpl",
)
CREDENTIAL_VARIABLES = (
    "COPILOTD_API_KEY", "MAGPIE_API_KEY", "DEEPSEEK_API_KEY",
    "CONTEXT7_API_KEY", "GITHUB_PERSONAL_ACCESS_TOKEN",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "YYLX_API_KEY",
    "CODEX_API_KEY", "PI_API_KEY", "OPENCODE_API_KEY", "LITELLM_API_KEY",
    "ROUTER_MAESTRO_API_KEY", "COPILOT_PROXY_API_KEY",
)
BEHAVIOR = {
    "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
    "PI_CLIPBOARD_OSC52": "1",
    "PI_STATUSLINE_STARSHIP": "C:/Users/fixture/scoop/apps/starship/current/starship.exe",
    "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0",
}


@unittest.skipUnless(CHEZMOI, "chezmoi is required")
class PiEnvironmentTemplateTests(unittest.TestCase):
    def environment_section(self, path):
        rendered = render_template(path)
        if path.startswith("readonly_Documents/"):
            return rendered.split("#endregion Environment Variables", 1)[0]
        # Every registry operation is converted to a disposable process write.
        self.assertEqual(rendered.count("[Environment]::SetEnvironmentVariable("), rendered.count(', "User")'))
        return rendered.replace(', "User")', ', "Process")')

    def test_templates_neither_decrypt_export_nor_clean_credentials(self):
        for path in TEMPLATES:
            with self.subTest(path=path):
                source = (REPO_ROOT / path).read_text("utf-8")
                self.assertNotIn("decrypt", source)
                self.assertNotIn("$secrets", source)
                section = self.environment_section(path)
                for name in CREDENTIAL_VARIABLES:
                    self.assertNotIn(name, section)
                self.assertNotIn("Remove-Item Env:", section)
                self.assertNotIn("$null", section)

    @unittest.skipUnless(POWERSHELL, "PowerShell 7 is required")
    def test_non_secret_behavior_and_inherited_credentials_are_preserved(self):
        observed = [*CREDENTIAL_VARIABLES, *BEHAVIOR, "ANTHROPIC_BASE_URL"]
        inherited = {name: "fixture-inherited-value" for name in CREDENTIAL_VARIABLES}
        inherited["ANTHROPIC_BASE_URL"] = "https://external.example.test"
        for path in TEMPLATES:
            with self.subTest(path=path):
                script = self.environment_section(path)
                names = ",".join("'" + name + "'" for name in observed)
                result = subprocess.run(
                    [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                     "$ErrorActionPreference = 'Stop'\n" + script + "\n$values = @{}\n"
                     + f"foreach ($name in @({names})) {{ $values[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }}\n"
                     + "$values | ConvertTo-Json -Compress"],
                    env={**os.environ, **inherited}, capture_output=True, text=True,
                    encoding="utf-8", timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                actual = json.loads(result.stdout)
                for name, value in {**inherited, **BEHAVIOR}.items():
                    self.assertEqual(actual[name], value, name)

    def test_manual_cleanup_is_not_invoked_by_setup(self):
        cleanup = (REPO_ROOT / "docs/cleanup-llm-environment.ps1").read_text("utf-8")
        self.assertIn("[switch]$Apply", cleanup)
        self.assertIn("SupportsShouldProcess", cleanup)
        self.assertIn("if (-not $Apply)", cleanup)
        self.assertNotIn("GetEnvironmentVariables(", cleanup)
        for path in (REPO_ROOT / ".chezmoiscripts").glob("*"):
            for line in path.read_text("utf-8").splitlines():
                if "cleanup-llm-environment.ps1" in line:
                    self.assertTrue(line.lstrip().startswith("#"))


if __name__ == "__main__":
    unittest.main()
