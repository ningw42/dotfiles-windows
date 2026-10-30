"""Opt-in compatibility checks for the installed upstream RTK implementation.

Run after RTK upgrades with: python -B tests/acceptance_rtk.py -v
The acceptance_ prefix excludes these checks from default unittest discovery.
Repository-owned integration behavior remains in test_rtk_integrations.py.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


RTK = shutil.which("rtk")
NODE = shutil.which("node")


@unittest.skipUnless(RTK, "RTK is required for native hook acceptance")
class CodexNativeRtkHookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="codex native rtk ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
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
