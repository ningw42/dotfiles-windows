"""Render provider credentials with fixtures; execute only in child-process envs."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHEZMOI = shutil.which("chezmoi")
POWERSHELL = shutil.which("pwsh")
PROVIDER_SECRETS = {
    "copilotd_api_key": "fixture-copilotd-key",
    "litellm_api_key": "fixture-litellm-key",
}
PROVIDER_ENVIRONMENT = {
    "COPILOTD_API_KEY": "fixture-copilotd-key",
    "LITELLM_API_KEY": "fixture-litellm-key",
}
OBSERVED_VARIABLES = [
    *PROVIDER_ENVIRONMENT, "CODEX_API_KEY", "PI_API_KEY", "OPENCODE_API_KEY",
    "DEEPSEEK_API_KEY", "MAGPIE_API_KEY",
    "ROUTER_MAESTRO_API_KEY", "COPILOT_PROXY_API_KEY",
]
SECRET_LOADER = 'include "secrets.yaml.age" | decrypt | fromYaml'
TEMPLATES = {
    "readonly_Documents/PowerShell/Microsoft.PowerShell_profile.ps1.tmpl":
        '$Env:MAGPIE_API_KEY = "fixture-magpie-key"',
    ".chezmoiscripts/run_onchange_windows-env.ps1.tmpl":
        '[Environment]::SetEnvironmentVariable("MAGPIE_API_KEY", "fixture-magpie-key", "User")',
}


@unittest.skipUnless(CHEZMOI, "chezmoi is required to render Pi environment templates")
class PiEnvironmentTemplateTests(unittest.TestCase):
    def render(self, path, *, magpie_key=False, secrets=None):
        source = (REPO_ROOT / path).read_text(encoding="utf-8")
        self.assertEqual(source.count(SECRET_LOADER), 1)
        # Substitute only the secret-loading boundary. The actual template,
        # including its optional-key guard, still runs through chezmoi's engine.
        source = source.replace(SECRET_LOADER, ".fixtureSecrets")
        fixture_secrets = {
            "context7_api_key": "fixture-context7-key",
            "github_personal_access_token": "fixture-github-token",
        }
        fixture_secrets.update(PROVIDER_SECRETS if secrets is None else secrets)
        if magpie_key:
            fixture_secrets["magpie_api_key"] = "fixture-magpie-key"

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
                        "fixtureSecrets": fixture_secrets,
                        "chezmoi": {"os": "windows", "homeDir": "C:/Users/fixture"},
                    }),
                    "--refresh-externals=never", "--no-tty", "--no-pager",
                ],
                input=source, capture_output=True, text=True, encoding="utf-8",
                cwd=root, env=env, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def evaluate(self, path, *, secrets, inherited=None):
        rendered = self.render(path, secrets=secrets)
        if path.startswith("readonly_Documents/"):
            # Do not execute interactive integrations or the rest of the profile.
            self.assertIn("#endregion Environment Variables", rendered)
            script = rendered.split("#endregion Environment Variables", 1)[0]
        else:
            # Redirect every persistent write to this disposable child process.
            # Refuse to execute if the template adds an unrecognized write shape.
            self.assertEqual(
                rendered.count("[Environment]::SetEnvironmentVariable("),
                rendered.count(', "User")'),
            )
            script = rendered.replace(', "User")', ', "Process")')
            self.assertNotIn('"User"', script)
        env = {
            key: value for key, value in os.environ.items()
            if key.upper() not in OBSERVED_VARIABLES
        }
        env.update(inherited or {})
        variables = ", ".join(f"'{name}'" for name in OBSERVED_VARIABLES)
        result = subprocess.run(
            [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
             "$ErrorActionPreference = 'Stop'\n" + script
             + "\n$values = @{}\n"
             + f"foreach ($name in @({variables})) {{\n"
             + "  $values[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')\n"
             + "}\n$values | ConvertTo-Json -Compress"],
            env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    @unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for fixture evaluation")
    def test_provider_fields_export_distinct_keys_not_legacy_credentials(self):
        for path in TEMPLATES:
            with self.subTest(path=path):
                actual = self.evaluate(path, secrets={
                    **PROVIDER_SECRETS,
                    "pi_api_key": "fixture-retired-pi-key",
                    "codex_api_key": "fixture-legacy-codex-key",
                }, inherited={name: "fixture-stale-key" for name in OBSERVED_VARIABLES})
                for name, value in PROVIDER_ENVIRONMENT.items():
                    self.assertEqual(actual[name], value)
                self.assertFalse(actual["CODEX_API_KEY"])
                self.assertFalse(actual["PI_API_KEY"])
                self.assertFalse(actual["OPENCODE_API_KEY"])

    def test_missing_provider_fields_render_without_legacy_fallback(self):
        for path in TEMPLATES:
            for secrets in ({}, {
                "codex_api_key": "fixture-legacy-codex-key",
                "pi_api_key": "fixture-retired-pi-key",
                "opencode_api_key": "fixture-retired-opencode-key",
            }):
                with self.subTest(path=path, legacy=bool(secrets)):
                    rendered = self.render(path, secrets=secrets)
                    self.assertNotIn("<no value>", rendered)
                    self.assertNotIn("fixture-legacy-codex-key", rendered)
                    self.assertNotIn("fixture-retired-pi-key", rendered)
                    self.assertNotIn("fixture-retired-opencode-key", rendered)
                    for variable in PROVIDER_ENVIRONMENT:
                        self.assertNotIn(variable, rendered)

    @unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for fixture evaluation")
    def test_unprovisioned_providers_preserve_external_keys_but_never_copy_legacy_keys(self):
        for path in TEMPLATES:
            for external in (False, True):
                with self.subTest(path=path, external=external):
                    inherited = {
                        name: f"external-{name}" for name in PROVIDER_ENVIRONMENT
                    } if external else {}
                    actual = self.evaluate(path, secrets={
                        "copilotd_api_key": "fixture-copilotd-key",
                        "codex_api_key": "fixture-legacy-codex-key",
                        "pi_api_key": "fixture-retired-pi-key",
                    }, inherited=inherited)
                    self.assertEqual(actual["COPILOTD_API_KEY"], "fixture-copilotd-key")
                    self.assertEqual(actual["LITELLM_API_KEY"], inherited.get("LITELLM_API_KEY"))

    @unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for fixture evaluation")
    def test_generic_export_is_cleared_with_or_without_legacy_secret(self):
        for path in TEMPLATES:
            for legacy in (False, True):
                with self.subTest(path=path, legacy=legacy):
                    secrets = dict(PROVIDER_SECRETS)
                    if legacy:
                        secrets["codex_api_key"] = "fixture-legacy-codex-key"
                    actual = self.evaluate(path, secrets=secrets, inherited={
                        name: "fixture-stale-key" for name in OBSERVED_VARIABLES
                    })
                    for name, value in PROVIDER_ENVIRONMENT.items():
                        self.assertEqual(actual[name], value)
                    # .NET's Process target can report a cleared variable as empty.
                    for name in ("CODEX_API_KEY", "PI_API_KEY", "OPENCODE_API_KEY"):
                        self.assertFalse(actual[name])

    @unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for fixture evaluation")
    def test_provider_fields_can_explicitly_share_a_value(self):
        for path in TEMPLATES:
            with self.subTest(path=path):
                actual = self.evaluate(path, secrets={
                    field: "fixture-intentionally-shared-key" for field in PROVIDER_SECRETS
                })
                for name in PROVIDER_ENVIRONMENT:
                    self.assertEqual(actual[name], "fixture-intentionally-shared-key")
                self.assertFalse(actual["CODEX_API_KEY"])

    @unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for fixture evaluation")
    def test_provider_credentials_are_literal_powershell_strings(self):
        value = "fixture-$env:USERPROFILE-`n-\"-'quoted'"
        for path in TEMPLATES:
            with self.subTest(path=path):
                actual = self.evaluate(path, secrets={
                    field: value for field in PROVIDER_SECRETS
                })
                for name in PROVIDER_ENVIRONMENT:
                    self.assertEqual(actual[name], value)

    @unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for fixture evaluation")
    def test_deepseek_cleanup_and_magpie_external_key_policy_are_unchanged(self):
        for path in TEMPLATES:
            for present in (False, True):
                with self.subTest(path=path, present=present):
                    actual = self.evaluate(path, secrets={
                        "deepseek_api_key": "fixture-deepseek-key",
                        "magpie_api_key": "fixture-magpie-key",
                    } if present else {}, inherited={
                        "DEEPSEEK_API_KEY": "external-deepseek-key",
                        "MAGPIE_API_KEY": "external-magpie-key",
                    })
                    if present:
                        self.assertEqual(actual["DEEPSEEK_API_KEY"], "fixture-deepseek-key")
                        self.assertEqual(actual["MAGPIE_API_KEY"], "fixture-magpie-key")
                    else:
                        self.assertFalse(actual["DEEPSEEK_API_KEY"])
                        self.assertEqual(actual["MAGPIE_API_KEY"], "external-magpie-key")

    @unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for fixture evaluation")
    def test_retired_provider_keys_are_cleared_even_if_old_secret_fields_remain(self):
        retired = {
            "router_maestro_api_key": "fixture-retired-router-key",
            "copilot_proxy_api_key": "fixture-retired-proxy-key",
            "opencode_api_key": "fixture-retired-opencode-key",
        }
        for path in TEMPLATES:
            for present in (False, True):
                with self.subTest(path=path, old_fields=present):
                    secrets = {**PROVIDER_SECRETS, **(retired if present else {})}
                    rendered = self.render(path, secrets=secrets)
                    for value in retired.values():
                        self.assertNotIn(value, rendered)
                    actual = self.evaluate(path, secrets=secrets, inherited={
                        "ROUTER_MAESTRO_API_KEY": "external-router-key",
                        "COPILOT_PROXY_API_KEY": "external-proxy-key",
                        "OPENCODE_API_KEY": "external-opencode-key",
                    })
                    for name in (
                        "ROUTER_MAESTRO_API_KEY", "COPILOT_PROXY_API_KEY", "OPENCODE_API_KEY",
                    ):
                        self.assertFalse(actual[name])
                    for name, value in PROVIDER_ENVIRONMENT.items():
                        self.assertEqual(actual[name], value)

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
