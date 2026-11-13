"""Exercise the agent generator with isolated upstream sources and output files."""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from llm_test_support import CHEZMOI, render_template


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / ".chezmoiscripts/run_after_pi-subagents-agents.ps1.tmpl"
POWERSHELL = shutil.which("pwsh")
NODE = shutil.which("node")
HOME_TEMPLATE = '{{ .chezmoi.homeDir | replace "\\\\" "/" }}'
AGENT_MODELS = {
    "Explore": "magpie-responses/gpt-5.6-sol",
    "Plan": "magpie-responses/gpt-6-astra",
    "general-purpose": None,
}

# Deliberately conflicting upstream pins prove local policy wins. Distinct
# prompts and inherited metadata prove generation still follows upstream.
DEFAULT_AGENTS = """export const DEFAULT_AGENTS = new Map(
  ["Explore", "Plan", "general-purpose"].map(name => [name, {
    description: `${name} upstream description`,
    systemPrompt: `${name} upstream prompt`,
    builtinToolNames: ["read", "bash"],
    promptMode: name === "general-purpose" ? "append" : "replace",
    model: "upstream/model",
    runInBackground: false,
    thinking: "high",
  }]),
);
"""
SERIALIZER = """import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { parseAgentFrontmatter } from "./custom-agents.js";
import type { AgentConfig } from "./types.js";

export function serializeAgentFile(cfg: AgentConfig): string {
  const fields = [
    `description: ${JSON.stringify(cfg.description)}`,
    `tools: ${cfg.builtinToolNames.join(", ")}`,
    `prompt_mode: ${cfg.promptMode}`,
  ];
  if (cfg.displayName) fields.push(`display_name: ${cfg.displayName}`);
  if (cfg.model) fields.push(`model: ${cfg.model}`);
  if (cfg.thinking) fields.push(`thinking: ${cfg.thinking}`);
  if (cfg.extensions === false) fields.push("extensions: false");
  if (cfg.runInBackground !== undefined) fields.push(`run_in_background: ${cfg.runInBackground}`);
  return `---\\n${fields.join("\\n")}\\n---\\n\\n${cfg.systemPrompt}\\n`;
}
"""


@unittest.skipUnless(POWERSHELL and NODE and CHEZMOI, "PowerShell 7, Node.js 22+, and chezmoi are required")
class PiBuiltinAgentGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pi agents test ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.distribution = self.root / "distribution"
        self.sources = self.distribution / "node_modules/@tintinweb/pi-subagents/src"
        self.sources.mkdir(parents=True)
        self.output = self.root / "agents"
        self.script = self.root / "generate.ps1"
        self.defaults = self.sources / "default-agents.ts"
        self.defaults.write_text(DEFAULT_AGENTS, encoding="utf-8")
        self.serializer = self.sources / "agent-file-toggle.ts"
        self.serializer.write_text(SERIALIZER, encoding="utf-8")
        (self.sources / "types.ts").write_text(
            "export type AgentConfig = Record<string, any>;\n", encoding="utf-8"
        )

        self.template = GENERATOR.read_text(encoding="utf-8")
        self.write_generator()

    def write_generator(self):
        # Render the Windows-only wrapper and home defaults into a temporary
        # fixture. Only dependency lookup changes: use PATH's Node instead of
        # requiring a real Scoop installation on the test host.
        script = render_template(str(GENERATOR), text=self.template, home=self.root.as_posix())
        node_assignment = "$node = Join-Path $env:USERPROFILE 'scoop/apps/nodejs/current/node.exe'"
        self.assertIn(node_assignment, script)
        script = script.replace(node_assignment, "$node = '" + NODE.replace("'", "''") + "'")
        self.assertNotIn("{{", script)
        self.script.write_text(script, encoding="utf-8")

    def generate(self):
        return subprocess.run(
            [
                POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive",
                "-File", str(self.script),
                "-PiDistributionRoot", str(self.distribution),
                "-OutputDirectory", str(self.output),
            ],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            cwd=self.root,
        )

    def test_all_managed_agents_pin_background_and_preserve_upstream_content(self):
        result = self.generate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({path.stem for path in self.output.glob("*.md")}, set(AGENT_MODELS))
        for name, model in AGENT_MODELS.items():
            with self.subTest(agent=name):
                content = (self.output / f"{name}.md").read_text(encoding="utf-8")
                self.assertEqual(re.findall(r"(?m)^run_in_background: (.*)$", content), ["true"])
                self.assertEqual(re.findall(r"(?m)^model: (.*)$", content), [model] if model else [])
                self.assertIn(f"description: {json.dumps(name + ' upstream description')}\n", content)
                self.assertIn(f"\n{name} upstream prompt\n", content)
                self.assertIn("tools: read, bash\n", content)
                self.assertIn("thinking: high\n", content)
                mode = "append" if name == "general-purpose" else "replace"
                self.assertIn(f"prompt_mode: {mode}\n", content)

    def test_reapply_is_idempotent_and_refreshes_upstream_prompts(self):
        first = self.generate()
        self.assertEqual(first.returncode, 0, first.stderr)
        paths = list(self.output.glob("*.md"))
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
        second = self.generate()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(
            {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}, before
        )

        self.defaults.write_text(DEFAULT_AGENTS.replace("upstream prompt", "updated prompt"), encoding="utf-8")
        third = self.generate()
        self.assertEqual(third.returncode, 0, third.stderr)
        for path in paths:
            self.assertIn("updated prompt", path.read_text(encoding="utf-8"))

    def customize_explore(self, fields):
        self.template, count = re.subn(
            r"(?ms)^    Explore = @\{\n.*?^    \}",
            "    Explore = @{\n" + fields + "    }",
            self.template,
        )
        self.assertEqual(count, 1)
        self.write_generator()

    def test_overrides_replace_lists_remove_fields_and_preserve_false(self):
        self.customize_explore(
            "        displayName = 'Scout'\n"
            "        model = $null\n"
            "        thinking = $null\n"
            "        builtinToolNames = @('find')\n"
            "        extensions = $false\n"
            "        runInBackground = $false\n"
        )
        result = self.generate()
        self.assertEqual(result.returncode, 0, result.stderr)
        content = (self.output / "Explore.md").read_text(encoding="utf-8")
        self.assertIn("display_name: Scout\n", content)
        self.assertIn("tools: find\n", content)
        self.assertIn("extensions: false\n", content)
        self.assertIn("run_in_background: false\n", content)
        self.assertNotRegex(content, r"(?m)^(model|thinking):")
        self.assertIn("Explore upstream prompt\n", content)
        self.assertFalse((self.output / "Scout.md").exists())

    def test_omitted_fields_inherit_and_empty_lists_replace_upstream(self):
        self.customize_explore("        builtinToolNames = @()\n")
        result = self.generate()
        self.assertEqual(result.returncode, 0, result.stderr)
        content = (self.output / "Explore.md").read_text(encoding="utf-8")
        self.assertIn("model: upstream/model\n", content)
        self.assertIn("thinking: high\n", content)
        self.assertIn("run_in_background: false\n", content)
        self.assertIn("tools: \n", content)

    def test_null_background_override_removes_upstream_pin(self):
        self.customize_explore("        runInBackground = $null\n")
        result = self.generate()
        self.assertEqual(result.returncode, 0, result.stderr)
        content = (self.output / "Explore.md").read_text(encoding="utf-8")
        self.assertNotRegex(content, r"(?m)^run_in_background:")
        self.assertIn("model: upstream/model\n", content)

    def test_missing_model_serialization_fails_before_publishing(self):
        self.serializer.write_text(
            SERIALIZER.replace('  if (cfg.model) fields.push(`model: ${cfg.model}`);\n', ""),
            encoding="utf-8",
        )
        result = self.generate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("model pin was not applied", result.stderr)
        self.assertFalse(self.output.exists())

    def test_missing_background_serialization_fails_before_publishing(self):
        self.serializer.write_text(
            SERIALIZER.replace(
                '  if (cfg.runInBackground !== undefined) fields.push(`run_in_background: ${cfg.runInBackground}`);\n',
                "",
            ), encoding="utf-8",
        )
        result = self.generate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("background execution pin was not applied", result.stderr)
        self.assertFalse(self.output.exists())

    def test_missing_builtin_fails_before_publishing(self):
        self.defaults.write_text(
            DEFAULT_AGENTS + '\nDEFAULT_AGENTS.delete("Plan");\n', encoding="utf-8"
        )
        result = self.generate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pi-subagents has no built-in Plan agent", result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
