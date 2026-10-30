"""RTK hook ownership, isolated initialization, and native plugin regressions."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHEZMOI = shutil.which("chezmoi")
POWERSHELL = shutil.which("pwsh")
RTK = shutil.which("rtk")
NODE = shutil.which("node")


@unittest.skipUnless(CHEZMOI, "chezmoi is required for real template rendering")
class CodexRtkConfigTests(unittest.TestCase):
    def test_native_rewrite_hook_is_trusted_without_changing_auth_or_herdr(self):
        with tempfile.TemporaryDirectory(prefix="codex rtk render ") as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            home = root / "home with spaces"
            home.mkdir()
            config = root / "chezmoi.json"
            config.write_text("{}", encoding="utf-8")
            rendered = {}
            for name in ("hooks.json", "config.toml"):
                result = subprocess.run(
                    [
                        CHEZMOI, "execute-template", "--config", str(config),
                        "--source", str(source), "--destination", str(home),
                        "--persistent-state", str(root / "state.boltdb"),
                        "--cache", str(root / "cache"), "--no-tty", "--no-pager",
                        "--refresh-externals=never", "--override-data",
                        json.dumps({
                            "chezmoi": {"homeDir": str(home)},
                            "codex_provider": "copilotd",
                        }),
                    ],
                    input=(REPO_ROOT / "dot_codex" / f"{name}.tmpl").read_text(
                        encoding="utf-8"
                    ),
                    capture_output=True, text=True, encoding="utf-8", timeout=30,
                    env={
                        key: value for key, value in os.environ.items()
                        if not key.upper().startswith("CHEZMOI_")
                    },
                    cwd=root,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                rendered[name] = result.stdout

            hooks = json.loads(rendered["hooks.json"])["hooks"]
            settings = tomllib.loads(rendered["config.toml"])
            self.assertEqual(set(hooks), {"SessionStart", "PreToolUse"})
            group = hooks["PreToolUse"][0]
            self.assertEqual(group, {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": "rtk hook codex"}],
            })
            # Match Codex/Nix's normalized definition, not the input JSON bytes.
            handler = group["hooks"][0]
            normalized = {
                "event_name": "pre_tool_use",
                "matcher": group["matcher"],
                "hooks": [{
                    "async": handler.get("async", False),
                    "command": handler["command"],
                    "timeout": handler.get("timeout", 600),
                    "type": handler["type"],
                }],
            }
            digest = hashlib.sha256(json.dumps(
                normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")).hexdigest()
            hook_path = str(home / ".codex" / "hooks.json")
            trust = settings["hooks"]["state"]
            self.assertEqual(
                trust[f"{hook_path}:pre_tool_use:0:0"]["trusted_hash"],
                f"sha256:{digest}",
            )
            self.assertEqual(len(trust), 2)
            self.assertEqual(
                trust[f"{hook_path}:session_start:0:0"]["trusted_hash"],
                "sha256:06548a65d143720b4561305061a21564fd877484854338649a2f447e27994852",
            )
            # The trust hash is tied to this reviewed definition, not merely
            # the script filename. Changes require a new native hooks/list hash.
            self.assertEqual(hooks["SessionStart"], [{
                "hooks": [{
                    "type": "command",
                    "command": (
                        "pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass "
                        f'-File "{home.as_posix()}/.codex/herdr-agent-state.ps1" session'
                    ),
                    "timeout": 10,
                }],
            }])
            self.assertTrue(settings["features"]["hooks"])
            self.assertEqual(settings["model_provider"], "copilotd")
            self.assertEqual(
                settings["model_providers"]["copilotd"]["auth"]["args"][-1],
                "[Console]::Out.Write($env:COPILOTD_API_KEY)",
            )


@unittest.skipUnless(POWERSHELL and RTK, "PowerShell 7 and RTK are required")
class CodexRtkAwarenessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="codex rtk publish ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "managed codex home"
        self.home.mkdir()
        self.script = self.root / "publish.ps1"
        template = (
            REPO_ROOT / ".chezmoiscripts/run_onchange_rtk-init.ps1.tmpl"
        ).read_text(encoding="utf-8")
        generator = template[
            template.index("function Initialize-CodexRtk("):
            template.index("\nInitialize-CodexRtk -CodexHome")
        ]
        self.script.write_text(
            "param([string]$CodexHome, [string]$RtkPath)\n"
            "$ErrorActionPreference = 'Stop'\n"
            + generator
            + "\nInitialize-CodexRtk -CodexHome $CodexHome -RtkPath $RtkPath\n",
            encoding="utf-8",
        )
        self.environment = os.environ.copy()
        self.environment.update({
            "CODEX_HOME": str(self.root / "ambient codex home"),
            "HOME": str(self.root / "profile"),
            "USERPROFILE": str(self.root / "profile"),
            "APPDATA": str(self.root / "appdata"),
            "LOCALAPPDATA": str(self.root / "localappdata"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "TMP": str(self.root),
            "TEMP": str(self.root),
        })

    def publish(self, executable=RTK):
        return subprocess.run(
            [
                POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                str(self.script), "-CodexHome", str(self.home),
                "-RtkPath", executable,
            ],
            cwd=self.root, env=self.environment, capture_output=True, text=True,
            encoding="utf-8", timeout=30,
        )

    def test_preserves_managed_settings_and_user_policy_and_is_idempotent(self):
        protected = {
            "config.toml": b"# Keep managed config and its hook trust\n",
            "hooks.json": b'{"hooks":{"SessionStart":[]}}\n',
        }
        for name, content in protected.items():
            (self.home / name).write_bytes(content)
        instructions = self.home / "AGENTS.md"
        instructions.write_text(
            "# User policy\nPreserve unrelated instructions.\n\n@RTK.md\n",
            encoding="utf-8",
        )

        result = self.publish()

        self.assertEqual(result.returncode, 0, result.stderr)
        generated = instructions.read_text(encoding="utf-8")
        self.assertIn("# User policy\nPreserve unrelated instructions.", generated)
        self.assertEqual(generated.count(f"@{self.home / 'RTK.md'}"), 1)
        self.assertNotIn("chezmoi-rtk-codex-", generated)
        self.assertIn(
            "rtk-owned", (self.home / "RTK.md").read_text(encoding="utf-8")
        )
        before = {path.name: path.read_bytes() for path in self.home.iterdir()}
        repeated = self.publish()
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(
            {path.name: path.read_bytes() for path in self.home.iterdir()}, before
        )
        for name, content in protected.items():
            self.assertEqual((self.home / name).read_bytes(), content)
        self.assertFalse((self.root / "ambient codex home").exists())
        self.assertEqual(list(self.root.glob("chezmoi-rtk-codex-*")), [])

    def test_native_processor_rewrites_bash_commands(self):
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
            "permission_mode": "default",
            "session_id": "rtk-regression-test",
            "cwd": str(self.root),
        }
        result = subprocess.run(
            [RTK, "hook", "codex"], input=json.dumps(payload),
            cwd=self.root, env=self.environment, capture_output=True, text=True,
            encoding="utf-8", timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["updatedInput"]["command"], "rtk git status")

    def test_fresh_home_receives_only_awareness_documents(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            {path.name for path in self.home.iterdir()}, {"AGENTS.md", "RTK.md"}
        )
        self.assertEqual(
            (self.home / "AGENTS.md").read_text(encoding="utf-8").strip(),
            f"@{self.home / 'RTK.md'}",
        )

    def test_generator_failure_leaves_existing_documents_unchanged(self):
        instructions = self.home / "AGENTS.md"
        instructions.write_bytes(b"# Keep policy\n\n@RTK.md\n")
        before = instructions.read_bytes()
        result = self.publish(str(self.root / "missing-rtk.exe"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(instructions.read_bytes(), before)
        self.assertFalse((self.home / "RTK.md").exists())
        self.assertEqual(list(self.root.glob("chezmoi-rtk-codex-*")), [])


@unittest.skipUnless(POWERSHELL, "PowerShell 7 is required")
class OpenCodeRtkInitTests(unittest.TestCase):
    def test_native_plugin_has_one_owner_and_the_legacy_adapter_is_retired(self):
        self.assertFalse((REPO_ROOT / "dot_config/opencode/plugins/rtk.js").exists())
        self.assertFalse((REPO_ROOT / "dot_config/opencode/plugins/rtk.ts").exists())
        removals = (REPO_ROOT / ".chezmoiremove").read_text(encoding="utf-8").splitlines()
        self.assertIn(".config/opencode/plugins/rtk.js", removals)
        self.assertNotIn(".config/opencode/plugins/rtk.ts", removals)

    def test_init_isolates_claude_restores_environment_and_cleans_up_on_failure(self):
        source = (REPO_ROOT / ".chezmoiscripts/run_onchange_rtk-init.ps1.tmpl").read_text("utf-8")
        function = source[
            source.index("function Initialize-OpenCodeRtk("):
            source.index("\nInitialize-OpenCodeRtk\n")
        ]
        for inherited in (False, True):
            for exit_code in (0, 7):
                with self.subTest(inherited=inherited, exit_code=exit_code):
                    with tempfile.TemporaryDirectory(prefix="opencode rtk init ") as temporary:
                        root = Path(temporary)
                        protected = root / "real claude config"
                        protected.mkdir()
                        settings = protected / "settings.json"
                        settings.write_bytes(b'{"fixture":"keep"}\n')
                        env = os.environ.copy()
                        env.pop("CLAUDE_CONFIG_DIR", None)
                        env.update({"FIXTURE_PROTECTED": str(protected), "FIXTURE_EXIT": str(exit_code)})
                        if inherited:
                            env["CLAUDE_CONFIG_DIR"] = str(protected)
                        script = (
                            "$ErrorActionPreference = 'Stop'\n"
                            "function Invoke-FixtureRtk {\n"
                            "  if ($env:CLAUDE_CONFIG_DIR -eq $env:FIXTURE_PROTECTED) { throw 'Claude config was not isolated' }\n"
                            "  $script:work = $env:CLAUDE_CONFIG_DIR\n"
                            "  $script:arguments = @($args)\n"
                            "  [IO.File]::WriteAllText((Join-Path $script:work 'CLAUDE.md'), '@RTK.md')\n"
                            "  $global:LASTEXITCODE = [int]$env:FIXTURE_EXIT\n"
                            "}\n"
                            + function
                            + "\n$failed = $false\n"
                            "try { Initialize-OpenCodeRtk -RtkPath Invoke-FixtureRtk } catch {\n"
                            "  if ($_ -notlike '*initialization failed*') { throw }\n"
                            "  $failed = $true\n"
                            "}\n"
                            "@{ arguments = $script:arguments; failed = $failed; work = $script:work;\n"
                            "   cleaned = -not (Test-Path -LiteralPath $script:work);\n"
                            "   restored = $env:CLAUDE_CONFIG_DIR } | ConvertTo-Json -Compress\n"
                        )
                        result = subprocess.run(
                            [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                            cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        actual = json.loads(result.stdout)
                        self.assertEqual(actual["arguments"], ["init", "-g", "--opencode", "--no-patch"])
                        self.assertEqual(actual["failed"], exit_code != 0)
                        self.assertTrue(actual["cleaned"])
                        self.assertTrue(Path(actual["work"]).name.startswith("chezmoi-rtk-opencode-"))
                        self.assertEqual(actual["restored"], str(protected) if inherited else None)
                        self.assertEqual(settings.read_bytes(), b'{"fixture":"keep"}\n')
                        self.assertEqual([path.name for path in protected.iterdir()], ["settings.json"])


@unittest.skipUnless(RTK and NODE, "RTK 1.1+ and Node.js with TypeScript support are required")
class OpenCodeNativeRtkPluginTests(unittest.TestCase):
    def test_native_plugin_registration_rewrites_and_permission_boundaries(self):
        with tempfile.TemporaryDirectory(prefix="opencode native rtk ") as temporary:
            root = Path(temporary)
            env = os.environ.copy()
            env.pop("RTK_DISABLED", None)
            env.update({
                "CLAUDE_CONFIG_DIR": str(root / "claude"),
                "OPENCODE_CONFIG": str(root / "global.json"),
            })
            (root / "global.json").write_text("{}", encoding="utf-8")
            # RTK ignores HOME overrides on Windows. Its verbose dry-run exposes
            # the embedded artifact without deploying any files or initializing
            # Claude. If already current, read the reported existing artifact.
            preview = subprocess.run(
                [RTK, "-v", "init", "-g", "--opencode", "--no-patch", "--dry-run"],
                cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            match = re.search(
                r"\[dry-run\] would (?:create|update) OpenCode plugin: [^\n]+\n"
                r"\[dry-run\] content:\n(.*?)(?=\n\[dry-run\])",
                preview.stdout, re.S,
            )
            if match:
                plugin_source = match[1]
            else:
                match = re.search(r"OpenCode plugin already up to date: ([^\r\n]+)", preview.stderr)
                self.assertIsNotNone(match, preview.stdout + preview.stderr)
                plugin_source = Path(match[1]).read_text("utf-8")
            self.assertIn('id: "rtk"', plugin_source)
            plugin = root / "rtk.ts"
            plugin.write_text(plugin_source, encoding="utf-8")
            script = """
import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
const { default: plugin } = await import(process.env.FIXTURE_PLUGIN);
let handler;
await plugin.setup({ tool: { hook: async (name, callback) => {
  assert.equal(name, "execute.before");
  handler = callback;
} } });
assert.equal(typeof handler, "function");
const event = { tool: "shell", input: { command: "git status" } };
await handler(event);
assert.equal(event.input.command, "rtk git status");
process.env.RTK_DISABLED = "1";
const disabled = { tool: "shell", input: { command: "git status" } };
await handler(disabled);
assert.equal(disabled.input.command, "git status");
delete process.env.RTK_DISABLED;
writeFileSync("opencode.json", JSON.stringify({
  agents: { restricted: { permissions: [
    { action: "shell", resource: "git status", effect: "deny" },
  ] } },
}));
const denied = { tool: "shell", agent: "restricted", input: { command: "git status" } };
await handler(denied);
assert.equal(denied.input.command, "git status");
const otherTool = { tool: "read", input: { command: "git status" } };
await handler(otherTool);
assert.equal(otherTool.input.command, "git status");
"""
            result = subprocess.run(
                [NODE, "--input-type=module", "-e", script],
                cwd=root, env={**env, "FIXTURE_PLUGIN": plugin.as_uri()},
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((root / "claude").exists(), "RTK dry-run wrote Claude files")


if __name__ == "__main__":
    unittest.main()
