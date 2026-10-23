import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh")
REVIEWED_VERSIONS = {
    "pi": 9,
    "claude": 11,
    "codex": 10,
    "copilot": 4,
    "opencode": 13,
}


def integration(integration_id, version):
    return (
        "# installed by herdr\n"
        f"# HERDR_INTEGRATION_ID={integration_id}\n"
        f"# HERDR_INTEGRATION_VERSION={version}\n"
    )


@unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for integration publishing")
class HerdrIntegrationGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="herdr gate test ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "generated.ps1"
        self.destination = self.root / "published.ps1"
        self.script = self.root / "publish.ps1"

        template = (
            REPO_ROOT / ".chezmoiscripts/run_onchange_herdr-integrations.ps1.tmpl"
        ).read_text(encoding="utf-8")
        # Exercise the real version table and publisher without running HerdR's
        # installer, rendering home paths, or touching the deployed profile.
        versions = template[
            template.index("$expectedIntegrationVersions ="):
            template.index("if (-not (Test-Path -LiteralPath $HerdrPath")
        ]
        publisher = template[
            template.index("function Test-HerdrOwnedFile("):
            template.index("function Set-TextFile(")
        ]
        self.script.write_text(
            'param([string]$Source, [string]$Destination, [string]$IntegrationId)\n'
            "$ErrorActionPreference = 'Stop'\n"
            + versions
            + publisher
            + "\nSet-HerdrIntegrationFile -Source $Source -Destination $Destination "
            "-IntegrationId $IntegrationId "
            "-ExpectedVersion $expectedIntegrationVersions[$IntegrationId]\n",
            encoding="utf-8",
        )

    def publish(self, integration_id):
        return subprocess.run(
            [
                POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive",
                "-File", str(self.script),
                "-Source", str(self.source),
                "-Destination", str(self.destination),
                "-IntegrationId", integration_id,
            ],
            capture_output=True,
            text=True,
        )

    def test_reviewed_versions_replace_owned_older_integrations(self):
        for integration_id, version in REVIEWED_VERSIONS.items():
            with self.subTest(integration=integration_id, version=version):
                self.source.write_text(
                    integration(integration_id, version), encoding="utf-8"
                )
                self.destination.write_text(
                    integration(integration_id, version - 1), encoding="utf-8"
                )

                result = self.publish(integration_id)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.destination.read_bytes(), self.source.read_bytes())
                self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_unreviewed_versions_leave_destination_unchanged(self):
        for integration_id, expected in REVIEWED_VERSIONS.items():
            for version in (expected - 1, expected + 1):
                with self.subTest(integration=integration_id, version=version):
                    self.source.write_text(
                        integration(integration_id, version), encoding="utf-8"
                    )
                    self.destination.write_text(
                        integration(integration_id, expected - 1), encoding="utf-8"
                    )
                    before = self.destination.read_bytes()

                    result = self.publish(integration_id)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        f"expected v{expected}, generated v{version}", result.stderr
                    )
                    self.assertEqual(self.destination.read_bytes(), before)

    def test_reviewed_versions_do_not_overwrite_non_herdr_files(self):
        for integration_id, version in REVIEWED_VERSIONS.items():
            with self.subTest(integration=integration_id, version=version):
                self.source.write_text(
                    integration(integration_id, version), encoding="utf-8"
                )
                self.destination.write_text("# user-owned hook\n", encoding="utf-8")
                before = self.destination.read_bytes()

                result = self.publish(integration_id)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Refusing to overwrite non-HerdR file", result.stderr)
                self.assertEqual(self.destination.read_bytes(), before)


@unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for TUI mark publishing")
class HerdrOpenCodeTuiMarkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="herdr tui test ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "generated-tui.jsonc"
        self.destination = self.root / "tui.jsonc"
        self.legacy = self.root / "tui.json"
        self.script = self.root / "publish-tui.ps1"

        template = (
            REPO_ROOT / ".chezmoiscripts/run_onchange_herdr-integrations.ps1.tmpl"
        ).read_text(encoding="utf-8")
        # Exercise the real TUI mark publisher without running HerdR's installer
        # or touching the deployed OpenCode config.
        set_text_file = template[
            template.index("function Set-TextFile("):
            template.index("function Test-HerdrClaudeHookConfig(")
        ]
        tui_publisher = template[
            template.index("function Get-HerdrOpenCodeTuiPluginSpecs("):
            template.index("function Test-HerdrCopilotHookConfig(")
        ]
        self.script.write_text(
            "param([string]$Source, [string]$Destination, [string]$Legacy = '')\n"
            "$ErrorActionPreference = 'Stop'\n"
            "$utf8NoBom = [Text.UTF8Encoding]::new($false)\n"
            + set_text_file
            + tui_publisher
            + "\nif (-not [string]::IsNullOrEmpty($Legacy)) {\n"
            + "    $specs = Get-HerdrOpenCodeTuiPluginSpecs $Source\n"
            + "    Remove-HerdrLegacyOpenCodeTuiConfig -Path $Legacy -PluginSpecs $specs\n"
            + "}\n"
            + "Set-HerdrOpenCodeTuiConfig -Source $Source -Destination $Destination\n",
            encoding="utf-8",
        )

    def publish(self, legacy=None):
        command = [
            POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive",
            "-File", str(self.script),
            "-Source", str(self.source),
            "-Destination", str(self.destination),
        ]
        if legacy is not None:
            command += ["-Legacy", str(legacy)]
        return subprocess.run(command, capture_output=True, text=True)

    def test_publishes_generated_registration_idempotently(self):
        self.source.write_text(
            '{\n  "plugin": ["./herdr-tui-session.js"]\n}\n', encoding="utf-8"
        )

        result = self.publish()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(self.destination.read_text(encoding="utf-8")),
            {"plugin": ["./herdr-tui-session.js"]},
        )
        before = self.destination.read_bytes()
        self.assertEqual(self.publish().returncode, 0)
        self.assertEqual(self.destination.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_refuses_user_owned_tui_config(self):
        self.source.write_text(
            '{\n  "plugin": ["./herdr-tui-session.js"]\n}\n', encoding="utf-8"
        )
        user_config = (
            '{\n  "plugin": ["./herdr-tui-session.js"],\n  "theme": "system"\n}\n'
        )
        self.destination.write_text(user_config, encoding="utf-8")

        result = self.publish()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Refusing to overwrite non-managed OpenCode TUI config", result.stderr
        )
        self.assertEqual(self.destination.read_text(encoding="utf-8"), user_config)

    def test_rejects_unreviewed_generated_format(self):
        self.source.write_text(
            '{\n  "plugin": ["./herdr-tui-session.js"],\n  "theme": "system"\n}\n',
            encoding="utf-8",
        )

        result = self.publish()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has an unexpected format", result.stderr)
        self.assertFalse(self.destination.exists())

    def test_replaces_herdr_uninstall_residue(self):
        self.source.write_text(
            '{\n  "plugin": ["./herdr-tui-session.js"]\n}\n', encoding="utf-8"
        )
        self.destination.write_text("{}\n", encoding="utf-8")

        result = self.publish()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(self.destination.read_text(encoding="utf-8")),
            {"plugin": ["./herdr-tui-session.js"]},
        )

    def test_removes_previous_managed_tui_json_marker(self):
        self.source.write_text(
            '{\n  "plugin": ["./herdr-tui-session.js"]\n}\n', encoding="utf-8"
        )
        self.legacy.write_text(
            '{\n  "plugin": [\n    "./herdr-tui-session.js"\n  ]\n}\n',
            encoding="utf-8",
        )

        result = self.publish(legacy=self.legacy)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.legacy.exists())
        self.assertEqual(
            json.loads(self.destination.read_text(encoding="utf-8")),
            {"plugin": ["./herdr-tui-session.js"]},
        )

    def test_preserves_foreign_legacy_tui_json(self):
        self.source.write_text(
            '{\n  "plugin": ["./herdr-tui-session.js"]\n}\n', encoding="utf-8"
        )
        foreign = (
            '{\n  "plugin": ["./herdr-tui-session.js"],\n  "theme": "system"\n}\n'
        )
        self.legacy.write_text(foreign, encoding="utf-8")

        result = self.publish(legacy=self.legacy)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.legacy.read_text(encoding="utf-8"), foreign)
        self.assertTrue(self.destination.exists())


@unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for CLI config publishing")
class HerdrOpenCodeCliConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="herdr cli test ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "generated-cli.json"
        self.destination = self.root / "cli.json"
        self.script = self.root / "publish-cli.ps1"

        template = (
            REPO_ROOT / ".chezmoiscripts/run_onchange_herdr-integrations.ps1.tmpl"
        ).read_text(encoding="utf-8")
        set_text_file = template[
            template.index("function Set-TextFile("):
            template.index("function Test-HerdrClaudeHookConfig(")
        ]
        cli_publisher = template[
            template.index("function Test-HerdrOpenCodeCliConfig("):
            template.index("function Get-HerdrOpenCodeTuiPluginSpecs(")
        ]
        self.script.write_text(
            "param([string]$Source, [string]$Destination)\n"
            "$ErrorActionPreference = 'Stop'\n"
            "$utf8NoBom = [Text.UTF8Encoding]::new($false)\n"
            + set_text_file
            + cli_publisher
            + "\nSet-HerdrOpenCodeCliConfig -Source $Source -Destination $Destination\n",
            encoding="utf-8",
        )

    def publish(self):
        return subprocess.run(
            [
                POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive",
                "-File", str(self.script),
                "-Source", str(self.source),
                "-Destination", str(self.destination),
            ],
            capture_output=True,
            text=True,
        )

    def test_replaces_uninstall_residue(self):
        self.source.write_text(
            '{\n  "plugins": ["./herdr-opencode"]\n}\n', encoding="utf-8"
        )
        residues = {
            "empty": "{}\n",
            "preferences": (
                '{\n  "$schema": "https://opencode.ai/v2/cli.json",\n'
                '  "theme": {\n    "name": "catppuccin"\n  }\n}\n'
            ),
        }
        expected = {
            "$schema": "https://opencode.ai/v2/cli.json",
            "theme": {"name": "catppuccin"},
            "plugins": ["./herdr-opencode"],
        }

        for label, residue in residues.items():
            with self.subTest(residue=label):
                self.destination.write_text(residue, encoding="utf-8")

                result = self.publish()

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    json.loads(self.destination.read_text(encoding="utf-8")),
                    expected,
                )

    def test_refuses_user_owned_config(self):
        self.source.write_text(
            '{\n  "plugins": ["./herdr-opencode"]\n}\n', encoding="utf-8"
        )
        user_config = (
            '{\n  "$schema": "https://opencode.ai/v2/cli.json",\n'
            '  "theme": {\n    "name": "catppuccin"\n  },\n'
            '  "plugins": ["./herdr-opencode"],\n'
            '  "extra": true\n}\n'
        )
        self.destination.write_text(user_config, encoding="utf-8")

        result = self.publish()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Refusing to overwrite non-managed OpenCode CLI config", result.stderr
        )
        self.assertEqual(self.destination.read_text(encoding="utf-8"), user_config)


if __name__ == "__main__":
    unittest.main()
