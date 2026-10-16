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


if __name__ == "__main__":
    unittest.main()
