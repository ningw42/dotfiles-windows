"""Exercise the HerdR Core DSC resource without Scoop or the deployed home."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh")


def core_resource():
    document = (REPO_ROOT / "configuration.dsc.yaml").read_text("utf-8")
    match = re.search(
        r"(?ms)^    - resource: PSDscResources/Script\n"
        r"      id: ScoopHerdrCore\n(?P<body>.*?)(?=^    - resource:|\Z)",
        document,
    )
    if match is None:
        raise AssertionError("Missing ScoopHerdrCore DSC resource")
    body = match.group("body")
    scripts = {
        name: textwrap.dedent(script)
        for name, script in re.findall(
            r"(?m)^        (TestScript|SetScript|GetScript): \|\n((?:^          .*\n)+)",
            body,
        )
    }
    return body, scripts


class HerdrCoreDeclarationTests(unittest.TestCase):
    def test_resource_uses_main_bucket_and_managed_executable(self):
        body, scripts = core_resource()
        self.assertIn("dependsOn:\n        - ScoopBootstrap\n", body)
        self.assertEqual(set(scripts), {"TestScript", "SetScript", "GetScript"})
        for script in scripts.values():
            self.assertIn(r"$env:USERPROFILE\scoop\apps\herdr-core\current\herdr-core.exe", script)
            self.assertIn("-PathType Leaf", script)
        self.assertIn(
            '& "$env:USERPROFILE\\scoop\\shims\\scoop.cmd" install main/herdr-core',
            scripts["SetScript"],
        )


@unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for isolated DSC checks")
class HerdrCoreProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="herdr core dsc ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "isolated home"
        self.home.mkdir()
        self.executable = self.home / "scoop/apps/herdr-core/current/herdr-core.exe"
        self.calls = self.home / "scoop-calls.txt"
        self.spy = self.root / "scoop-spy.ps1"
        self.spy.write_text(
            "Add-Content -LiteralPath (Join-Path $env:USERPROFILE 'scoop-calls.txt') -Value ($args -join ' ')\n"
            "if ($env:CORE_TEST_FAIL -eq '1') { $global:LASTEXITCODE = 23; return }\n"
            "if ($env:CORE_TEST_OMIT_EXE -ne '1') {\n"
            "    $exe = Join-Path $env:USERPROFILE 'scoop/apps/herdr-core/current/herdr-core.exe'\n"
            "    New-Item -ItemType Directory -Path (Split-Path -Parent $exe) -Force | Out-Null\n"
            "    Set-Content -LiteralPath $exe -Value 'fixture executable marker, never run'\n"
            "}\n"
            "$global:LASTEXITCODE = 0\n",
            encoding="utf-8",
        )
        _, scripts = core_resource()
        command = '& "$env:USERPROFILE\\scoop\\shims\\scoop.cmd"'
        self.assertEqual(scripts["SetScript"].count(command), 1)
        # Substitute only the external Scoop command. All resource logic and
        # managed path checks execute unchanged against an isolated profile.
        scripts["SetScript"] = scripts["SetScript"].replace(command, "& $ScoopSpy")
        self.scripts = {}
        for action, body in scripts.items():
            path = self.root / f"{action}.ps1"
            path.write_text(
                "param([string]$ScoopSpy)\n$ErrorActionPreference = 'Stop'\n"
                + "$result = & {\n" + body + "}\n"
                + "$result | ConvertTo-Json -Compress\n",
                encoding="utf-8",
            )
            self.scripts[action] = path

    def run_action(self, action, **overrides):
        env = dict(os.environ)
        env.update({
            "USERPROFILE": str(self.home), "HOME": str(self.home),
            "CORE_TEST_FAIL": "0", "CORE_TEST_OMIT_EXE": "0", **overrides,
        })
        return subprocess.run(
            [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
             str(self.scripts[action]), "-ScoopSpy", str(self.spy)],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=30,
        )

    def assert_action_value(self, action, value):
        result = self.run_action(action)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), value)

    def test_install_and_repeat_are_idempotent(self):
        self.executable.parent.mkdir(parents=True)
        self.assert_action_value("TestScript", False)
        self.assert_action_value("GetScript", {"Result": "NotInstalled"})
        result = self.run_action("SetScript")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.executable.is_file())
        self.assert_action_value("TestScript", True)
        self.assert_action_value("GetScript", {"Result": "Installed"})
        result = self.run_action("SetScript")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.read_text().splitlines(), ["install main/herdr-core"])

    def test_scoop_failure_is_reported(self):
        result = self.run_action("SetScript", CORE_TEST_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Failed to install HerdR Core via Scoop (exit 23)", result.stderr)
        self.assertFalse(self.executable.exists())

    def test_success_without_managed_executable_is_rejected(self):
        result = self.run_action("SetScript", CORE_TEST_OMIT_EXE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Scoop did not create the managed HerdR Core executable", result.stderr)
        self.assertFalse(self.executable.exists())


if __name__ == "__main__":
    unittest.main()
