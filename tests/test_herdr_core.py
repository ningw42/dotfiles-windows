"""Exercise Core provisioning and skill generation without changing the deployed home."""

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
CHEZMOI = shutil.which("chezmoi")


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


@unittest.skipUnless(POWERSHELL and CHEZMOI, "PowerShell and chezmoi are required")
class HerdrCoreSkillTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="herdr core skill ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home ' quoted"
        self.home.mkdir()
        self.target = self.home / ".local/share/herdr-core/skills/herdr-core"
        self.marker = self.target / "SKILL.md"
        self.links = [self.home / path / "herdr-core" for path in (
            ".agents/skills", ".claude/skills", ".codex/skills",
            ".copilot/skills", ".config/opencode/skills",
        )]
        self.manual = self.root / "manual.md"
        self.manual.write_bytes(b"# hc manual (herdr-core)\n\n" + "Fixture café manual.\n".encode())
        self.spy = self.root / "core-spy.ps1"
        self.spy.write_text(
            "if ($env:CORE_TEST_FAIL -eq '1') { [Console]::Error.Write('fixture error'); exit 19 }\n"
            "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n"
            "[Console]::Write([IO.File]::ReadAllText($env:CORE_MANUAL_PATH))\n",
            encoding="utf-8",
        )
        config = self.root / "config.json"
        config.write_text("{}", encoding="utf-8")
        source = self.root / "source"
        source.mkdir()
        template = (REPO_ROOT / ".chezmoiscripts/run_after_herdr-core-skill.ps1.tmpl").read_text("utf-8")
        result = subprocess.run(
            [CHEZMOI, "execute-template", "--config", str(config), "--config-format", "json",
             "--source", str(source), "--destination", str(self.home),
             "--persistent-state", str(self.root / "state.boltdb"),
             "--cache", str(self.root / "cache"), "--no-tty", "--no-pager",
             "--override-data", json.dumps({"chezmoi": {
                 "os": "windows", "homeDir": self.home.as_posix(), "destDir": self.home.as_posix(),
             }})],
            input=template, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("home '' quoted/scoop/apps/herdr-core/current/herdr-core.exe", result.stdout)
        # Exercise the actual process capture/error handling with pwsh as the
        # fixture binary; substitute only its CLI arguments, not the publisher.
        argument = "    $startInfo.ArgumentList.Add('--skill')"
        self.assertEqual(result.stdout.count(argument), 1)
        spy_path = str(self.spy).replace("'", "''")
        replacement = "\n".join(
            f"    $startInfo.ArgumentList.Add('{arg}')"
            for arg in ("-NoLogo", "-NoProfile", "-NonInteractive", "-File", spy_path)
        )
        self.script = self.root / "publish.ps1"
        self.script.write_text(result.stdout.replace(argument, replacement), encoding="utf-8")

    def publish(self, *, executable=POWERSHELL, fail=False):
        env = dict(os.environ)
        env.update({"CORE_MANUAL_PATH": str(self.manual), "CORE_TEST_FAIL": "1" if fail else "0"})
        return subprocess.run(
            [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(self.script),
             "-CoreExecutable", executable, "-HomeRoot", str(self.home)],
            cwd=self.root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def test_publication_preserves_binary_manual_updates_and_repairs_links(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        first = self.marker.read_bytes()
        self.assertTrue(first.replace(b"\r\n", b"\n").startswith(b"---\nname: herdr-core\n"))
        self.assertTrue(first.endswith(self.manual.read_bytes()))
        self.assertIn(b"`HC_TERMINAL_ID`", first)
        self.assertIn(b"ask the user once this session", first)
        for link in self.links:
            self.assertTrue(link.is_symlink())
            self.assertEqual((link / "SKILL.md").read_bytes(), first)
        mtime = self.marker.stat().st_mtime_ns
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.marker.stat().st_mtime_ns, mtime)
        self.manual.write_bytes(b"# hc manual (herdr-core)\r\n\r\nUpdated runtime manual.\r\n")
        self.links[-1].unlink()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.read_bytes().endswith(self.manual.read_bytes()))
        self.assertNotEqual(self.marker.read_bytes(), first)
        self.assertTrue(self.links[-1].is_symlink())
        self.assertEqual(list(self.target.glob("*.tmp")), [])

    def test_missing_or_failing_binary_does_not_publish(self):
        result = self.publish(executable=str(self.root / "missing.exe"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HerdR Core is missing", result.stderr)
        result = self.publish(fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--skill failed (exit 19)", result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertFalse(any(os.path.lexists(link) for link in self.links))

    def test_unexpected_manual_or_new_frontmatter_preserves_existing_skill(self):
        self.assertEqual(self.publish().returncode, 0)
        before = self.marker.read_bytes()
        for data in (b"", b"usage: hc", b"---\nname: herdr-core\n---\nnew format\n"):
            with self.subTest(manual=data):
                self.manual.write_bytes(data)
                result = self.publish()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("empty or unexpected manual", result.stderr)
                self.assertEqual(self.marker.read_bytes(), before)

    def test_foreign_link_is_rejected_before_writing_skill(self):
        self.links[-1].mkdir(parents=True)
        foreign = self.links[-1] / "mine.txt"
        foreign.write_text("preserve me", encoding="utf-8")
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-owned HerdR Core skill link", result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertFalse(any(os.path.lexists(link) for link in self.links[:-1]))
        self.assertEqual(foreign.read_text(), "preserve me")

    def test_foreign_skill_is_not_overwritten(self):
        self.target.mkdir(parents=True)
        self.marker.write_bytes(b"user-owned skill\n")
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-owned HerdR Core skill", result.stderr)
        self.assertEqual(self.marker.read_bytes(), b"user-owned skill\n")
        self.assertFalse(any(os.path.lexists(link) for link in self.links))

    def test_redirected_parent_is_not_followed(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.home / ".agents").symlink_to(outside, target_is_directory=True)
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("redirected HerdR Core output parent", result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
