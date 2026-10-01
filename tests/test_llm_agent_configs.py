import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
USER_SKILLS = {
    "close-code-review",
    "develop-and-squash",
    "develop-and-submit-pr",
    "simplification-review",
    "subagent-parity",
    "traceability",
    "unlimited-subagent-turns",
}
GPT_MODELS = [
    "gpt-6-luna",
    "gpt-5.6-sol-fast",
    "gpt-6.1-sol",
    "gpt-6-astra",
]
DEEPSEEK_MODELS = ["deepseek-flash", "deepseek-v4-pro"]
HOME_TEMPLATE = '{{ .chezmoi.homeDir | replace "\\\\" "/" }}'


def load_json(path):
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def load_opencode_config():
    source = (REPO_ROOT / "dot_config/opencode/opencode.json.tmpl").read_text(
        encoding="utf-8"
    )
    return json.loads(source.replace(HOME_TEMPLATE, "C:/Users/fixture"))


class ModelCatalogTests(unittest.TestCase):
    def test_opencode_catalog_and_policy_match_nixfiles_projection(self):
        config = load_opencode_config()
        self.assertEqual(config["model"], "copilotd-openai/gpt-6.1-sol")
        self.assertEqual(
            config["plugins"], ["-opencode.config.compatibility"]
        )
        self.assertEqual(
            config["skills"],
            ["C:/Users/fixture/.agents/skills", ".agents/skills"],
        )
        self.assertEqual(
            config["enabled_providers"],
            ["copilotd-openai", "deepseek-messages"],
        )
        self.assertEqual(set(config["permission"]["skill"]), USER_SKILLS)

        providers = config["provider"]
        self.assertEqual(set(providers), {"copilotd-openai", "deepseek-messages"})
        self.assertEqual(
            list(providers["copilotd-openai"]["models"]), GPT_MODELS
        )
        self.assertEqual(
            list(providers["deepseek-messages"]["models"]), DEEPSEEK_MODELS
        )
        self.assertEqual(
            providers["copilotd-openai"]["options"]["apiKey"],
            "{env:COPILOTD_API_KEY}",
        )
        self.assertEqual(
            providers["deepseek-messages"]["options"],
            {
                "apiKey": "{env:DEEPSEEK_API_KEY}",
                "baseURL": "https://api.deepseek.com/anthropic/v1",
            },
        )
        self.assertEqual(
            providers["copilotd-openai"]["models"]["gpt-6.1-sol"]["limit"][
                "context"
            ],
            1_050_000,
        )
        self.assertEqual(
            providers["deepseek-messages"]["models"]["deepseek-flash"][
                "options"
            ]["effort"],
            "high",
        )

    def test_pi_catalog_and_cycle_defaults_match_nixfiles_projection(self):
        catalog = load_json("dot_pi/agent/models.json")
        settings = load_json("dot_pi/agent/settings.json")
        providers = catalog["providers"]

        self.assertEqual(set(providers), {"copilotd-openai", "deepseek-responses"})
        self.assertEqual(
            [model["id"] for model in providers["copilotd-openai"]["models"]],
            GPT_MODELS,
        )
        self.assertEqual(
            [model["id"] for model in providers["deepseek-responses"]["models"]],
            DEEPSEEK_MODELS,
        )
        self.assertNotIn(
            "compat", providers["copilotd-openai"]["models"][-1]
        )
        self.assertEqual(
            providers["deepseek-responses"]["models"][0]["thinkingLevelMap"],
            {"off": "none", "minimal": None, "medium": None, "max": "max"},
        )
        self.assertEqual(settings["defaultProvider"], "copilotd-openai")
        self.assertEqual(settings["defaultModel"], "gpt-6.1-sol")
        self.assertEqual(settings["defaultThinkingLevel"], "xhigh")
        self.assertEqual(settings["defaultTools"], ["+powershell", "+codemode"])
        self.assertEqual(
            settings["enabledModels"][-2:],
            [
                "deepseek-responses/deepseek-flash:high",
                "deepseek-responses/deepseek-v4-pro:high",
            ],
        )

    def test_native_and_adapter_pi_mcp_configs_stay_identical(self):
        self.assertEqual(
            load_json("dot_pi/agent/readonly_mcp.json"),
            load_json("dot_config/mcp/readonly_mcp.json"),
        )


class AgentDefaultTests(unittest.TestCase):
    def test_all_supported_agent_defaults_match_nixfiles(self):
        opencode = load_opencode_config()
        pi = load_json("dot_pi/agent/settings.json")
        copilot = json.loads(
            (REPO_ROOT / "dot_copilot/settings.json.tmpl")
            .read_text(encoding="utf-8")
            .replace(HOME_TEMPLATE, "C:/Users/fixture")
        )
        codex = (REPO_ROOT / "dot_codex/config.toml.tmpl").read_text(
            encoding="utf-8"
        )
        claude = (REPO_ROOT / "dot_claude/settings.json.tmpl").read_text(
            encoding="utf-8"
        )
        profile = (
            REPO_ROOT
            / "readonly_Documents/PowerShell/Microsoft.PowerShell_profile.ps1.tmpl"
        ).read_text(encoding="utf-8")

        self.assertEqual(opencode["model"], "copilotd-openai/gpt-6.1-sol")
        self.assertEqual(pi["defaultModel"], "gpt-6.1-sol")
        self.assertEqual(copilot["model"], "gpt-6.1-sol")
        self.assertRegex(codex, r'(?m)^model = "gpt-6\.1-sol"$')
        self.assertIn('"claude-opus-5-5"', claude)
        self.assertNotIn("ANTHROPIC_BASE_URL", claude)
        self.assertIn('claude --model "claude-opus-5-5[1m]"', profile)

    def test_opencode_human_only_commands_cover_every_local_skill(self):
        command_dir = REPO_ROOT / "dot_config/opencode/commands"
        command_names = {path.name.removesuffix(".md.tmpl") for path in command_dir.iterdir()}
        self.assertEqual(command_names, USER_SKILLS)
        for name in USER_SKILLS:
            command = (command_dir / f"{name}.md.tmpl").read_text(encoding="utf-8")
            self.assertIn(f'dot_agents/skills/{name}/SKILL.md', command)

    def test_pi_builtin_agent_routes_match_nixfiles(self):
        generator = (
            REPO_ROOT / ".chezmoiscripts/run_after_pi-subagents-agents.ps1.tmpl"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            generator,
            r"(?m)^\s*Explore = 'copilotd-openai/gpt-5\.6-sol-fast'$",
        )
        self.assertRegex(
            generator,
            r"(?m)^\s*Plan = 'copilotd-openai/gpt-6-astra'$",
        )
        self.assertRegex(generator, r"(?m)^\s*'general-purpose' = \$null$")

    def test_windows_provisioning_replaces_opencode_1_with_opencode_2(self):
        provisioning = (REPO_ROOT / "configuration.dsc.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("id: ScoopBucketVersions", provisioning)
        self.assertIn("$apps\\opencode2\\current", provisioning)
        self.assertIn("uninstall opencode", provisioning)
        self.assertIn("install versions/opencode2", provisioning)


if __name__ == "__main__":
    unittest.main()
