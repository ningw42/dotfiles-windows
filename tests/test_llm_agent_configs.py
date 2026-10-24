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
USER_SKILLS = {
    path.parent.name for path in (REPO_ROOT / "dot_agents/skills").glob("*/SKILL.md")
}
GPT_MODELS = [
    "gpt-6-luna",
    "gpt-5.6-sol",
    "gpt-6.1-sol",
    "gpt-6-astra",
]
MAGPIE_RESPONSE_MODELS = [*GPT_MODELS, "deepseek-flash", "glm-5.3", "glm-5.3-flash"]
MAGPIE_GEMINI_MODELS = ["gemini-4-argon-contributor"]
HOME_TEMPLATE = '{{ .chezmoi.homeDir | replace "\\\\" "/" }}'


def load_json(path):
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def load_opencode_config():
    source = (REPO_ROOT / "dot_config/opencode/opencode.json.tmpl").read_text(
        encoding="utf-8"
    )
    return json.loads(source.replace(HOME_TEMPLATE, "C:/Users/fixture"))


def load_pi_builtin_agent_routes():
    generator = (
        REPO_ROOT / ".chezmoiscripts/run_after_pi-subagents-agents.ps1.tmpl"
    ).read_text(encoding="utf-8")
    return dict(re.findall(r"(?m)^\s*(Explore|Plan) = '([^']+)'$", generator))


@unittest.skipUnless(CHEZMOI, "chezmoi is required for real template rendering")
class CodexProviderRoutingTests(unittest.TestCase):
    def render_config(self, provider="copilotd", *, path="dot_codex/config.toml.tmpl", expected_error=None):
        with tempfile.TemporaryDirectory(prefix="codex-provider-render-") as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            source = root / "source"
            source.mkdir()
            config = root / "chezmoi.toml"
            data = {
                "codex_provider": provider,
                "colorscheme": "catppuccin-mocha",
                "password_manager": "bitwarden",
                "git_username": "Fixture User",
                "git_useremail": "fixture@example.test",
                "git_signingkey": "FIXTURE",
            }
            config.write_text(
                "[data]\n" + "".join(f"{key} = {json.dumps(value)}\n" for key, value in data.items()),
                encoding="utf-8",
            )
            template = (REPO_ROOT / path).read_text(encoding="utf-8")
            initializing = path == ".chezmoi.toml.tmpl"
            if initializing:
                # promptChoiceOnce exists only during init, not execute-template.
                # Init is confined to the fixture and never uses --apply.
                (source / path).write_text(template, encoding="utf-8")
                command = [CHEZMOI, "init"]
            else:
                command = [CHEZMOI, "execute-template", "--override-data", json.dumps({
                    "chezmoi": {"homeDir": str(home)},
                })]
            result = subprocess.run(
                [
                    *command, "--config", str(config),
                    "--source", str(source), "--destination", str(home),
                    "--persistent-state", str(root / "state.boltdb"),
                    "--cache", str(root / "cache"), "--no-tty", "--no-pager",
                    "--refresh-externals=never",
                ],
                input=None if initializing else template,
                capture_output=True, text=True, encoding="utf-8", timeout=30,
                env={
                    key: value for key, value in os.environ.items()
                    if not key.upper().startswith("CHEZMOI_")
                },
                cwd=root,
            )
            if expected_error:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)
                self.assertIn("chezmoi edit-config", result.stderr)
                return None
            self.assertEqual(result.returncode, 0, result.stderr)
            return tomllib.loads(config.read_text(encoding="utf-8") if initializing else result.stdout)

    def test_only_copilotd_is_registered_with_command_auth(self):
        providers = self.render_config()["model_providers"]
        self.assertEqual(set(providers), {"copilotd"})
        self.assertNotIn("env_key", providers["copilotd"])
        self.assertEqual(providers["copilotd"]["auth"], {
            "command": "pwsh",
            "args": ["-NoProfile", "-NonInteractive", "-Command",
                     "[Console]::Out.Write($env:COPILOTD_API_KEY)"],
            "timeout_ms": 5000,
            "refresh_interval_ms": 0,
        })

    @unittest.skipUnless(POWERSHELL, "PowerShell 7 is required for fixture auth commands")
    def test_auth_lookup_uses_provider_key_without_legacy_fallback(self):
        auth = self.render_config()["model_providers"]["copilotd"]["auth"]
        fixtures = {
            "COPILOTD_API_KEY": "fixture-copilotd-key",
            "LITELLM_API_KEY": "fixture-retired-litellm-key",
            "ROUTER_MAESTRO_API_KEY": "fixture-retired-router-key",
            "COPILOT_PROXY_API_KEY": "fixture-retired-proxy-key",
            "CODEX_API_KEY": "fixture-legacy-codex-key",
            "PI_API_KEY": "fixture-retired-pi-key",
            "OPENCODE_API_KEY": "fixture-retired-opencode-key",
        }
        # Auth commands print credentials: never let one inherit a real key.
        clean_env = {
            key: value for key, value in os.environ.items()
            if not key.upper().endswith("_API_KEY")
        }
        for present in (True, False):
            with self.subTest(present=present):
                env = {**clean_env, **fixtures}
                if not present:
                    del env["COPILOTD_API_KEY"]
                result = subprocess.run(
                    [POWERSHELL, *auth["args"]], env=env,
                    capture_output=True, text=True, encoding="utf-8", timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "fixture-copilotd-key" if present else "")

    def test_saved_provider_selection_and_endpoint_are_preserved(self):
        config = self.render_config()
        self.assertEqual(config["model_provider"], "copilotd")
        provider = config["model_providers"]["copilotd"]
        self.assertEqual(provider["base_url"], "https://copilotd.ningw.net/openai/v1")
        self.assertEqual(provider["wire_api"], "responses")
        self.assertEqual(provider["stream_idle_timeout_ms"], 600000)
        self.assertTrue(provider["supports_websockets"])

    def test_retired_saved_provider_requires_explicit_reselection(self):
        for path in ("dot_codex/config.toml.tmpl", ".chezmoi.toml.tmpl"):
            for retired in ("litellm", "agent-maestro", "router-maestro", "copilot-proxy"):
                with self.subTest(path=path, retired=retired):
                    self.render_config(retired, path=path, expected_error="retired")

    def test_init_choices_and_saved_active_provider_exclude_retired_providers(self):
        source = (REPO_ROOT / ".chezmoi.toml.tmpl").read_text(encoding="utf-8")
        self.assertIn('$codex_provider_choices := list "copilotd"', source)
        config = self.render_config(path=".chezmoi.toml.tmpl")
        self.assertEqual(config["data"]["codex_provider"], "copilotd")


@unittest.skipUnless(CHEZMOI, "chezmoi is required for real template rendering")
class ClaudeConfigTests(unittest.TestCase):
    def test_subscription_auth_and_model_effort(self):
        with tempfile.TemporaryDirectory(prefix="claude-config-render-") as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            home = root / "home"
            home.mkdir()
            config = root / "chezmoi.json"
            config.write_text("{}", encoding="utf-8")
            result = subprocess.run(
                [
                    CHEZMOI, "execute-template", "--config", str(config),
                    "--source", str(source), "--destination", str(home),
                    "--persistent-state", str(root / "state.boltdb"),
                    "--cache", str(root / "cache"), "--no-tty", "--no-pager",
                    "--refresh-externals=never", "--override-data",
                    json.dumps({
                        "chezmoi": {"homeDir": str(home)},
                        "agent_skills": {"sources": {}},
                    }),
                ],
                input=(REPO_ROOT / "dot_claude/settings.json.tmpl").read_text("utf-8"),
                capture_output=True, text=True, encoding="utf-8", timeout=30,
                env={
                    key: value for key, value in os.environ.items()
                    if not key.upper().startswith("CHEZMOI_")
                },
                cwd=root,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            settings = json.loads(result.stdout)

        self.assertNotIn("apiKeyHelper", settings)
        for key in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "ANTHROPIC_DEFAULT_FABLE_MODEL",
        ):
            with self.subTest(key=key):
                self.assertNotIn(key, settings["env"])
        self.assertEqual(settings["modelSettings"]["claude-opus-5-5"]["effortLevel"], "xhigh")


class ModelCatalogTests(unittest.TestCase):
    def test_opencode_catalog_and_policy_match_nixfiles_projection(self):
        config = load_opencode_config()
        self.assertEqual(config["model"], "magpie-responses/gpt-6.1-sol")
        self.assertEqual(
            config["plugins"], ["-opencode.config.compatibility"]
        )
        self.assertEqual(
            config["skills"],
            ["C:/Users/fixture/.agents/skills", ".agents/skills"],
        )
        self.assertEqual(
            config["enabled_providers"],
            ["magpie-generative-ai", "magpie-responses"],
        )
        self.assertEqual(config["permission"]["skill"], {name: "deny" for name in USER_SKILLS})

        providers = config["provider"]
        self.assertEqual(set(providers), {"magpie-generative-ai", "magpie-responses"})
        self.assertEqual(
            list(providers["magpie-responses"]["models"]), MAGPIE_RESPONSE_MODELS
        )
        self.assertEqual(
            list(providers["magpie-generative-ai"]["models"]), MAGPIE_GEMINI_MODELS
        )
        self.assertEqual(providers["magpie-responses"]["name"], "magpie (Responses)")
        self.assertEqual(
            providers["magpie-responses"]["options"],
            {
                "apiKey": "{env:MAGPIE_API_KEY}",
                "baseURL": "https://magpie.ningw.net/v1",
            },
        )
        self.assertEqual(
            providers["magpie-responses"]["models"]["gpt-6.1-sol"]["limit"][
                "context"
            ],
            1_050_000,
        )
        self.assertEqual(
            providers["magpie-responses"]["models"]["deepseek-flash"][
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
        # at 9c734f9; canonical JSON matches Nix's builtins.toJSON rendering.
        providers = load_opencode_config()["provider"]
        snapshot = json.dumps(
            providers, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "cd4aedbee7d3a73e1ebc2fa50c31610023920c9df7c578192c411a807cf24d5e",
        )

    def test_pi_catalog_and_cycle_defaults_match_nixfiles_projection(self):
        catalog = load_json("dot_pi/agent/models.json")
        settings = load_json("dot_pi/agent/settings.json")
        providers = catalog["providers"]

        self.assertEqual(
            set(providers),
            {"magpie-responses", "magpie-generative-ai"},
        )
        self.assertEqual(
            [model["id"] for model in providers["magpie-responses"]["models"]],
            MAGPIE_RESPONSE_MODELS,
        )
        self.assertEqual(
            [model["id"] for model in providers["magpie-generative-ai"]["models"]],
            MAGPIE_GEMINI_MODELS,
        )
        self.assertEqual(
            next(
                model for model in providers["magpie-responses"]["models"]
                if model["id"] == "deepseek-flash"
            )["thinkingLevelMap"],
            {"off": None, "minimal": None, "medium": None, "max": "max"},
        )
        self.assertEqual(settings["defaultProvider"], "magpie-responses")
        self.assertEqual(settings["defaultModel"], "gpt-6.1-sol")
        self.assertEqual(settings["defaultThinkingLevel"], "xhigh")
        self.assertEqual(settings["defaultTools"], ["+powershell", "+codemode"])
        self.assertEqual(
            settings["enabledModels"],
            [
                *[f"magpie-responses/{model}:xhigh" for model in GPT_MODELS],
                "magpie-responses/deepseek-flash:high",
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
            if model["id"] in GPT_MODELS:
                continue
            with self.subTest(model=model["id"]):
                self.assertEqual(
                    model["thinkingLevelMap"],
                    {"off": None, "minimal": None, "medium": None, "max": "max"},
                )
        flash = next(
            model for model in providers["magpie-responses"]["models"]
            if model["id"] == "deepseek-flash"
        )
        self.assertEqual(flash["id"], "deepseek-flash")
        self.assertEqual(flash["name"], "DeepSeek Flash")
        self.assertNotIn("deepseek-responses", providers)

    def test_pi_provider_metadata_matches_nixfiles_snapshot(self):
        # Full provider snapshot from nixfiles' llm-agents/tests/model-catalog.nix
        # at 9c734f9; canonical JSON matches Nix's builtins.toJSON rendering.
        providers = load_json("dot_pi/agent/models.json")["providers"]
        snapshot = json.dumps(
            providers, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "d7715553b5da78178001670188f1a43dfaa9da32f5f25f72d5702f0a49dc7e0e",
        )
        sol = next(
            model
            for model in providers["magpie-responses"]["models"]
            if model["id"] == "gpt-6.1-sol"
        )
        self.assertIsNone(sol["thinkingLevelMap"]["off"])

    def test_pi_configured_routes_reference_registered_models(self):
        providers = load_json("dot_pi/agent/models.json")["providers"]
        settings = load_json("dot_pi/agent/settings.json")
        routes = {
            "default": (
                f'{settings["defaultProvider"]}/{settings["defaultModel"]}'
                f':{settings["defaultThinkingLevel"]}'
            ),
            **{
                f"cycle-{index}": route
                for index, route in enumerate(settings["enabledModels"])
            },
            **{
                f"tier-{name}": route
                for name, route in load_json("dot_pi/workflows/model-tiers.json")["tiers"].items()
            },
            **{
                f"agent-{name}": route
                for name, route in load_pi_builtin_agent_routes().items()
            },
        }
        for name, route in routes.items():
            with self.subTest(route=name):
                model_ref, _, thinking = route.partition(":")
                provider_id, model_id = model_ref.split("/", 1)
                self.assertIn(provider_id, providers)
                models = {model["id"]: model for model in providers[provider_id]["models"]}
                self.assertIn(model_id, models)
                if thinking:
                    self.assertIn(
                        thinking, ("off", "minimal", "low", "medium", "high", "xhigh", "max")
                    )
                    default_effort = None if thinking in ("xhigh", "max") else thinking
                    self.assertIsNotNone(
                        models[model_id].get("thinkingLevelMap", {}).get(
                            thinking, default_effort
                        )
                    )

    def test_deepseek_flash_shared_display_rates_match_nixfiles(self):
        pi = load_json("dot_pi/agent/models.json")["providers"]
        opencode = load_opencode_config()["provider"]
        flash = next(m for m in pi["magpie-responses"]["models"] if m["id"] == "deepseek-flash")
        self.assertEqual(
            flash["cost"],
            {"input": 0.15, "output": 0.6, "cacheRead": 0.003, "cacheWrite": 0},
        )
        self.assertEqual(
            opencode["magpie-responses"]["models"]["deepseek-flash"]["cost"],
            {"input": 0.15, "output": 0.6, "cache_read": 0.003},
        )
        self.assertEqual(
            opencode["magpie-responses"]["models"]["deepseek-flash"]["name"],
            "DeepSeek Flash",
        )


class PiRuntimeConfigTests(unittest.TestCase):
    def test_pi_builtin_mcp_replaces_the_retired_adapter(self):
        # Built-in MCP reads the shared server configuration; the retired
        # adapter must not introduce a second owner.
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
        self.assertNotIn("-builtin:mcp", settings.get("extensions", []))
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
        profile = (
            REPO_ROOT
            / "readonly_Documents/PowerShell/Microsoft.PowerShell_profile.ps1.tmpl"
        ).read_text(encoding="utf-8")

        self.assertEqual(opencode["model"], "magpie-responses/gpt-6.1-sol")
        self.assertEqual(pi["defaultModel"], "gpt-6.1-sol")
        self.assertEqual(copilot["model"], "gpt-6.1-sol")
        self.assertRegex(codex, r'(?m)^model = "gpt-6\.1-sol"$')
        self.assertIn('claude --model "claude-opus-5-5[1m]"', profile)

    def test_opencode_human_only_commands_cover_every_local_skill(self):
        self.assertTrue(USER_SKILLS, "no repo-authored skills found")
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
        self.assertEqual(load_pi_builtin_agent_routes(), {
            "Explore": "magpie-responses/gpt-5.6-sol",
            "Plan": "magpie-responses/gpt-6-astra",
        })
        self.assertRegex(generator, r"(?m)^\s*'general-purpose' = \$null$")

    def test_pi_workflow_tiers_match_nixfiles(self):
        self.assertEqual(load_json("dot_pi/workflows/model-tiers.json"), {
            "tiers": {
                "small": "magpie-responses/gpt-5.6-sol:max",
                "medium": "magpie-responses/gpt-6.1-sol:max",
                "big": "magpie-responses/gpt-6-astra:max",
            },
        })

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
