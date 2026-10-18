import hashlib
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
    "subagent-unlimited-turns",
    "traceability",
}
GPT_MODELS = [
    "gpt-6-luna",
    "gpt-5.6-sol-fast",
    "gpt-6.1-sol",
    "gpt-6-astra",
]
DEEPSEEK_MODELS = ["deepseek-flash"]
MAGPIE_RESPONSE_MODELS = ["deepseek-v4.1-flash", "glm-5.3", "glm-5.3-flash"]
MAGPIE_GEMINI_MODELS = ["gemini-4-argon-contributor"]
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
        self.assertEqual(config["model"], "copilotd-responses/gpt-6.1-sol")
        self.assertEqual(
            config["plugins"], ["-opencode.config.compatibility"]
        )
        self.assertEqual(
            config["skills"],
            ["C:/Users/fixture/.agents/skills", ".agents/skills"],
        )
        self.assertEqual(
            config["enabled_providers"],
            [
                "copilotd-responses",
                "deepseek-responses",
                "magpie-generative-ai",
                "magpie-responses",
            ],
        )
        self.assertEqual(set(config["permission"]["skill"]), USER_SKILLS)

        providers = config["provider"]
        self.assertEqual(
            set(providers),
            {
                "copilotd-responses",
                "deepseek-responses",
                "magpie-generative-ai",
                "magpie-responses",
            },
        )
        self.assertEqual(
            list(providers["copilotd-responses"]["models"]), GPT_MODELS
        )
        self.assertEqual(
            list(providers["deepseek-responses"]["models"]), DEEPSEEK_MODELS
        )
        self.assertEqual(
            list(providers["magpie-responses"]["models"]), MAGPIE_RESPONSE_MODELS
        )
        self.assertEqual(
            list(providers["magpie-generative-ai"]["models"]), MAGPIE_GEMINI_MODELS
        )
        self.assertEqual(
            providers["copilotd-responses"]["name"], "copilotd (Responses)"
        )
        self.assertEqual(
            providers["copilotd-responses"]["options"]["apiKey"],
            "{env:COPILOTD_API_KEY}",
        )
        self.assertEqual(
            providers["deepseek-responses"]["options"],
            {
                "apiKey": "{env:DEEPSEEK_API_KEY}",
                "baseURL": "https://api.deepseek.com",
            },
        )
        self.assertEqual(
            providers["copilotd-responses"]["models"]["gpt-6.1-sol"]["limit"][
                "context"
            ],
            1_050_000,
        )
        self.assertEqual(
            providers["deepseek-responses"]["models"]["deepseek-flash"][
                "options"
            ]["reasoningEffort"],
            "high",
        )
        self.assertEqual(
            providers["magpie-generative-ai"]["models"][
                "gemini-4-argon-contributor"
            ]["options"],
            {
                "thinkingConfig": {
                    "includeThoughts": True,
                    "thinkingLevel": "medium",
                }
            },
        )
        for name, npm, base_url in (
            (
                "copilotd-responses",
                "@ai-sdk/openai",
                "https://copilotd.ningw.net/openai/v1",
            ),
            (
                "deepseek-responses",
                "@ai-sdk/openai",
                "https://api.deepseek.com",
            ),
            (
                "magpie-responses",
                "@ai-sdk/openai",
                "https://magpie.ningw.net/v1",
            ),
            (
                "magpie-generative-ai",
                "@ai-sdk/google",
                "https://magpie.ningw.net/v1beta",
            ),
        ):
            with self.subTest(provider=name):
                self.assertEqual(providers[name]["npm"], npm)
                self.assertEqual(providers[name]["options"]["baseURL"], base_url)

    def test_opencode_provider_metadata_matches_nixfiles_snapshot(self):
        # Full provider snapshot from nixfiles' llm-agents/tests/model-catalog.nix
        # at 0b0ed60; canonical JSON matches Nix's builtins.toJSON rendering.
        providers = load_opencode_config()["provider"]
        snapshot = json.dumps(
            providers, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "162ef1c963d266461e661a51f38ce417d558bddf5f2cef6e230d0dbd2606672b",
        )

    def test_pi_catalog_and_cycle_defaults_match_nixfiles_projection(self):
        catalog = load_json("dot_pi/agent/models.json")
        settings = load_json("dot_pi/agent/settings.json")
        providers = catalog["providers"]

        self.assertEqual(
            set(providers),
            {"copilotd-responses", "deepseek-responses", "magpie-responses", "magpie-generative-ai"},
        )
        self.assertEqual(
            [model["id"] for model in providers["copilotd-responses"]["models"]],
            GPT_MODELS,
        )
        self.assertEqual(
            [model["id"] for model in providers["deepseek-responses"]["models"]],
            DEEPSEEK_MODELS,
        )
        self.assertEqual(
            [model["id"] for model in providers["magpie-responses"]["models"]],
            MAGPIE_RESPONSE_MODELS,
        )
        self.assertEqual(
            [model["id"] for model in providers["magpie-generative-ai"]["models"]],
            MAGPIE_GEMINI_MODELS,
        )
        self.assertNotIn(
            "compat", providers["copilotd-responses"]["models"][-1]
        )
        self.assertEqual(
            providers["deepseek-responses"]["models"][0]["thinkingLevelMap"],
            {"off": None, "minimal": None, "medium": None, "max": "max"},
        )
        self.assertEqual(settings["defaultProvider"], "copilotd-responses")
        self.assertEqual(settings["defaultModel"], "gpt-6.1-sol")
        self.assertEqual(settings["defaultThinkingLevel"], "xhigh")
        self.assertEqual(settings["defaultTools"], ["+powershell", "+codemode"])
        self.assertEqual(
            settings["enabledModels"],
            [
                *[f"copilotd-responses/{model}:xhigh" for model in GPT_MODELS],
                "deepseek-responses/deepseek-flash:high",
                "magpie-responses/deepseek-v4.1-flash:high",
                "magpie-responses/glm-5.3:max",
                "magpie-responses/glm-5.3-flash:max",
                "magpie-generative-ai/gemini-4-argon-contributor:medium",
            ],
        )

    def test_pi_magpie_transports_and_thinking_match_nixfiles(self):
        providers = load_json("dot_pi/agent/models.json")["providers"]
        for name, api, base_url in (
            ("magpie-responses", "openai-responses", "https://magpie.ningw.net/v1"),
            ("magpie-generative-ai", "google-generative-ai", "https://magpie.ningw.net/v1beta"),
        ):
            with self.subTest(provider=name):
                provider = providers[name]
                self.assertEqual(provider["api"], api)
                self.assertEqual(provider["baseUrl"], base_url)
                self.assertEqual(provider["apiKey"], "$MAGPIE_API_KEY")
                self.assertTrue(all("compat" not in model for model in provider["models"]))

        gemini = providers["magpie-generative-ai"]["models"][0]
        self.assertEqual(gemini["thinkingLevelMap"], {"off": None, "minimal": None})
        self.assertEqual(gemini["input"], ["text", "image"])
        for model in providers["magpie-responses"]["models"]:
            with self.subTest(model=model["id"]):
                self.assertEqual(
                    model["thinkingLevelMap"],
                    {"off": None, "minimal": None, "medium": None, "max": "max"},
                )
        native_flash = providers["deepseek-responses"]["models"][0]
        magpie_flash = providers["magpie-responses"]["models"][0]
        self.assertEqual(
            {key: value for key, value in native_flash.items() if key not in {"id", "compat"}},
            {key: value for key, value in magpie_flash.items() if key != "id"},
        )

    def test_pi_provider_metadata_matches_nixfiles_snapshot(self):
        # Full provider snapshot from nixfiles' llm-agents/tests/model-catalog.nix
        # at 0b0ed60; canonical JSON matches Nix's builtins.toJSON rendering.
        providers = load_json("dot_pi/agent/models.json")["providers"]
        snapshot = json.dumps(
            providers, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "ac2e4588d97d25a7ec4e4114c6133dc005762fc8ed89070f5c477b0f6c6dfad1",
        )
        sol = next(
            model
            for model in providers["copilotd-responses"]["models"]
            if model["id"] == "gpt-6.1-sol"
        )
        self.assertIsNone(sol["thinkingLevelMap"]["off"])

    def test_deepseek_flash_shared_display_rates_match_nixfiles(self):
        pi = load_json("dot_pi/agent/models.json")["providers"]
        opencode = load_opencode_config()["provider"]
        for provider, model_id in (
            ("deepseek-responses", "deepseek-flash"),
            ("magpie-responses", "deepseek-v4.1-flash"),
        ):
            with self.subTest(provider=provider):
                model = next(m for m in pi[provider]["models"] if m["id"] == model_id)
                self.assertEqual(
                    model["cost"],
                    {"input": 0.15, "output": 0.6, "cacheRead": 0.003, "cacheWrite": 0},
                )
                self.assertEqual(
                    opencode[provider]["models"][model_id]["cost"],
                    {"input": 0.15, "output": 0.6, "cache_read": 0.003},
                )


class PiRuntimeConfigTests(unittest.TestCase):
    def test_pi_builtin_mcp_replaces_the_retired_adapter(self):
        # Pi 1.3 serves the shared remote servers natively; pi-distribution no
        # longer bundles the adapter that used to own them.
        self.assertFalse((REPO_ROOT / "dot_config/mcp/readonly_mcp.json").exists())
        removals = (REPO_ROOT / ".chezmoiremove").read_text(encoding="utf-8").splitlines()
        self.assertIn(".config/mcp/mcp.json", removals)

        servers = load_json("dot_pi/agent/readonly_mcp.json")["mcpServers"]
        self.assertEqual(set(servers), {"brave-search", "context7", "exa", "github"})
        self.assertEqual(
            servers["github"]["headers"],
            {"Authorization": "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"},
        )

    def test_pi_clipboard_forwarding_matches_nixfiles_wrapper(self):
        statements = {
            "readonly_Documents/PowerShell/Microsoft.PowerShell_profile.ps1.tmpl":
                '$Env:PI_CLIPBOARD_OSC52 = "1"',
            ".chezmoiscripts/run_onchange_windows-env.ps1.tmpl":
                '[Environment]::SetEnvironmentVariable("PI_CLIPBOARD_OSC52", "1", "User")',
        }
        for path, statement in statements.items():
            with self.subTest(path=path):
                source = (REPO_ROOT / path).read_text(encoding="utf-8")
                self.assertIn(statement, source)

    def test_pi_presentation_and_mcp_ownership_match_nixfiles(self):
        settings = load_json("dot_pi/agent/settings.json")
        self.assertEqual(settings["quietStartup"], "header")
        # Built-in MCP owns the shared servers, so nothing may exclude it.
        self.assertNotIn("extensions", settings)
        self.assertTrue(settings["hideThinkingBlock"])
        self.assertTrue(settings["showCacheMissNotices"])
        self.assertFalse(settings["showHardwareCursor"])
        self.assertEqual(settings["tuiMode"], "fullscreen")
        self.assertEqual(settings["markdown"], {"mermaid": "final"})
        self.assertEqual(settings["theme"], "catppuccin-mocha")

        # Preserve Windows-specific tools and the chezmoi-managed package path.
        self.assertEqual(settings["defaultTools"], ["+powershell", "+codemode"])
        self.assertEqual(settings["packages"], ["./packages/pi-distribution"])
        self.assertTrue(settings["shellPath"].endswith("\\bin\\bash.exe"))

    def test_pi_cc_configuration_matches_nixfiles(self):
        self.assertEqual(
            load_json("dot_pi/agent/pi-cc-extensions.json"),
            {
                "mode": "on",
                "diffViewMode": "auto",
                "diffIndicatorMode": "bars",
                "editDiffCollapsedLines": 0,
                "previewLines": 0,
                "scrollButtonMode": "native",
                "showStartupHeader": False,
                "enableCustomFooter": False,
            },
        )


class AgentDefaultTests(unittest.TestCase):
    def test_copilot_behavior_settings_match_nixfiles(self):
        settings = json.loads(
            (REPO_ROOT / "dot_copilot/settings.json.tmpl")
            .read_text(encoding="utf-8")
            .replace(HOME_TEMPLATE, "C:/Users/fixture")
        )
        self.assertTrue(settings["copyOnSelect"])
        self.assertFalse(settings["includeCoAuthoredBy"])
        self.assertEqual(settings["theme"], "default")
        self.assertNotIn("colorMode", settings)
        self.assertEqual(
            settings["allowedUrls"],
            [
                "https://learn.microsoft.com",
                "https://neo.vimhelp.org",
                "https://raw.githubusercontent.com",
            ],
        )

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

        self.assertEqual(opencode["model"], "copilotd-responses/gpt-6.1-sol")
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

    def test_subagent_unlimited_turns_rename_and_legacy_cleanup(self):
        skill_dir = REPO_ROOT / "dot_agents/skills/subagent-unlimited-turns"
        skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: subagent-unlimited-turns\n", skill)
        self.assertIn("disable-model-invocation: true\n", skill)
        metadata = (skill_dir / "agents/openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "Subagent Unlimited Turns"', metadata)
        self.assertIn("Use $subagent-unlimited-turns", metadata)
        self.assertIn("allow_implicit_invocation: false", metadata)

        removals = (REPO_ROOT / ".chezmoiremove").read_text(encoding="utf-8").splitlines()
        for target in (
            ".agents/skills/unlimited-subagent-turns",
            ".config/opencode/commands/unlimited-subagent-turns.md",
        ):
            with self.subTest(target=target):
                self.assertIn(target, removals)

    def test_pi_builtin_agent_routes_match_nixfiles(self):
        generator = (
            REPO_ROOT / ".chezmoiscripts/run_after_pi-subagents-agents.ps1.tmpl"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            generator,
            r"(?m)^\s*Explore = 'copilotd-responses/gpt-5\.6-sol-fast'$",
        )
        self.assertRegex(
            generator,
            r"(?m)^\s*Plan = 'copilotd-responses/gpt-6-astra'$",
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
