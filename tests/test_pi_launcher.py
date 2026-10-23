"""Exercise the real profile launcher with a disposable native-process boundary."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh")
PROFILE = "readonly_Documents/PowerShell/Microsoft.PowerShell_profile.ps1.tmpl"


@unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for launcher tests")
class PiLauncherTests(unittest.TestCase):
    def invoke(self, *, key="fixture-deepseek-key", arguments=(), pipeline=False,
               exit_code=0, missing_command=False, fail_on_nonzero=False):
        profile = (REPO_ROOT / PROFILE).read_text(encoding="utf-8")
        # Isolate the actual function without rendering secrets or loading any
        # interactive profile integrations. Nested braces remain indented.
        launcher = "Function pi\n" + profile.split("Function pi\n", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
        with tempfile.TemporaryDirectory(prefix="pi-launcher-") as temporary:
            root = Path(temporary)
            probe = root / "probe.py"
            probe.write_text(
                "import json, os, sys\n"
                "print(json.dumps({\n"
                "    'deepseek': os.environ.get('DEEPSEEK_API_KEY'),\n"
                "    'copilotd': os.environ.get('COPILOTD_API_KEY'),\n"
                "    'magpie': os.environ.get('MAGPIE_API_KEY'),\n"
                "    'arguments': sys.argv[1:],\n"
                "    'stdin': sys.stdin.read() if os.environ.get('FIXTURE_PIPELINE') == '1' else None,\n"
                "}, ensure_ascii=True))\n"
                "sys.exit(int(os.environ['FIXTURE_EXIT_CODE']))\n",
                encoding="utf-8",
            )
            script = root / "launch.ps1"
            script.write_text(
                "$ErrorActionPreference = 'Stop'\n"
                "$PSNativeCommandUseErrorActionPreference = ($env:FIXTURE_FAIL_ON_NONZERO -eq '1')\n"
                # Replace only executable discovery, not the native invocation.
                # A real Python child observes the launch environment and argv.
                "function Get-Command {\n"
                "  [CmdletBinding()] param($Name, $CommandType)\n"
                "  if ($Name -ne 'pi.exe' -or $CommandType -ne 'Application') { throw 'Unexpected command lookup' }\n"
                "  [pscustomobject]@{ Source = $env:FIXTURE_COMMAND }\n"
                "}\n"
                + launcher
                + "\n$before = @{ exists = (Test-Path Env:DEEPSEEK_API_KEY); value = $env:DEEPSEEK_API_KEY }\n"
                "$piArgs = @($env:FIXTURE_ARGUMENTS | ConvertFrom-Json)\n"
                "$failed = $false\n"
                "try {\n"
                "  if ($env:FIXTURE_PIPELINE -eq '1') {\n"
                "    @('first line', 'second line') | pi $env:FIXTURE_PROBE @piArgs\n"
                "  } else {\n"
                "    pi $env:FIXTURE_PROBE @piArgs\n"
                "  }\n"
                "} catch { $failed = $true }\n"
                "$after = @{ exists = (Test-Path Env:DEEPSEEK_API_KEY); value = $env:DEEPSEEK_API_KEY }\n"
                "$parent = @{ before = $before; after = $after; exitCode = $LASTEXITCODE; failed = $failed }\n"
                "Write-Output ('FIXTURE_PARENT:' + ($parent | ConvertTo-Json -Compress))\n",
                encoding="utf-8",
            )
            env = {
                name: value for name, value in os.environ.items()
                if not name.upper().endswith("_API_KEY")
            }
            env.update({
                "COPILOTD_API_KEY": "fixture-copilotd-key",
                "MAGPIE_API_KEY": "fixture-magpie-key",
                "FIXTURE_COMMAND": str(root / "missing.exe") if missing_command else sys.executable,
                "FIXTURE_PROBE": str(probe),
                "FIXTURE_ARGUMENTS": json.dumps(list(arguments)),
                "FIXTURE_PIPELINE": "1" if pipeline else "0",
                "FIXTURE_EXIT_CODE": str(exit_code),
                "FIXTURE_FAIL_ON_NONZERO": "1" if fail_on_nonzero else "0",
                "PYTHONIOENCODING": "utf-8",
            })
            if key is not None:
                env["DEEPSEEK_API_KEY"] = key
            result = subprocess.run(
                [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script)],
                env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        parent = json.loads(next(line.removeprefix("FIXTURE_PARENT:") for line in lines
                                 if line.startswith("FIXTURE_PARENT:")))
        child = next((json.loads(line) for line in lines if line.startswith("{")), None)
        self.assertEqual(parent["after"], parent["before"])
        return child, parent

    def test_only_deepseek_is_masked_and_parent_environment_is_restored(self):
        for key in ("fixture-deepseek-key", "", None):
            with self.subTest(key=key):
                child, parent = self.invoke(key=key)
                self.assertFalse(parent["failed"])
                self.assertIsNone(child["deepseek"])
                self.assertEqual(child["copilotd"], "fixture-copilotd-key")
                self.assertEqual(child["magpie"], "fixture-magpie-key")

    def test_arguments_are_forwarded_without_reinterpretation(self):
        arguments = ["a space", '"quoted"', "", "路径; $(not-a-command)", "--literal=value"]
        child, parent = self.invoke(arguments=arguments)
        self.assertFalse(parent["failed"])
        self.assertEqual(child["arguments"], arguments)

    def test_pipeline_input_is_forwarded(self):
        child, parent = self.invoke(pipeline=True)
        self.assertFalse(parent["failed"])
        self.assertEqual(child["stdin"], "first line\nsecond line\n")
        self.assertIsNone(child["deepseek"])

    def test_native_exit_code_survives_cleanup(self):
        child, parent = self.invoke(exit_code=7)
        self.assertIsNotNone(child)
        self.assertFalse(parent["failed"])
        self.assertEqual(parent["exitCode"], 7)

    def test_parent_key_is_restored_after_native_failure(self):
        child, parent = self.invoke(exit_code=7, fail_on_nonzero=True)
        self.assertIsNotNone(child)
        self.assertTrue(parent["failed"])
        self.assertEqual(parent["exitCode"], 7)

    def test_parent_key_is_restored_when_command_cannot_start(self):
        child, parent = self.invoke(missing_command=True)
        self.assertIsNone(child)
        self.assertTrue(parent["failed"])


if __name__ == "__main__":
    unittest.main()
