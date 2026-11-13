"""Read-only projection and validation tests; fixtures preserve pre-refactor JSON."""

from __future__ import annotations

import base64
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import render_llm_config as renderer

HOME = "C:/Users/Test User"
PWSH = "C:/Program Files/PowerShell/7/pwsh.exe"
FIXTURES = ROOT / "tests" / "fixtures" / "llm"


class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = renderer.load_data(ROOT)

    def setUp(self):
        self.data = copy.deepcopy(self.original)

    def render(self, target, *, home=HOME, pwsh=PWSH):
        return renderer.render(self.data, target, home, pwsh)

    def test_inventory_and_namespaces(self):
        self.assertEqual(set(self.data), {"providers", "models", "harnesses"})
        self.assertEqual(set(self.data["providers"]), {"copilotd", "magpie", "deepseek"})
        self.assertEqual(sum(len(p["endpoints"]) for p in self.data["providers"].values()), 7)
        self.assertEqual(len(self.data["models"]), 11)
        self.assertNotEqual(id(self.data["harnesses"]["pi"]["bindings"]),
                            id(self.data["harnesses"]["opencode"]["bindings"]))

    def test_pi_snapshot_changes_only_auth(self):
        expected = json.loads((FIXTURES / "pi-models.json").read_text(encoding="utf-8"))
        actual = self.render("pi-models")
        self.assertEqual(sum(len(p["models"]) for p in actual["providers"].values()), 11)
        for name, provider in actual["providers"].items():
            self.assertTrue(provider["apiKey"].startswith('!"' + PWSH + '"'))
            provider["apiKey"] = expected["providers"][name]["apiKey"]
        self.assertEqual(actual, expected)

    def test_opencode_snapshot_is_unchanged(self):
        expected = json.loads((FIXTURES / "opencode.json").read_text(encoding="utf-8"))
        expected = {key: expected[key] for key in ("provider", "enabled_providers", "model")}
        actual = self.render("opencode")
        self.assertEqual(actual, expected)
        for provider in actual["provider"].values():
            self.assertEqual(provider["options"]["apiKey"], "{env:MAGPIE_API_KEY}")
            self.assertNotIn("tiers", next(iter(provider["models"].values()))["cost"])

    def test_pi_settings_tiers_and_agents_match_current_policy(self):
        self.assertEqual(self.render("pi-settings"), {
            "defaultProvider": "magpie-responses", "defaultModel": "gpt-6-astra",
            "defaultThinkingLevel": "xhigh", "enabledModels": [
                "magpie-responses/gpt-6-luna:xhigh", "magpie-responses/gpt-5.6-sol:xhigh",
                "magpie-responses/gpt-6.1-sol:xhigh", "magpie-responses/gpt-6-astra:xhigh",
                "magpie-responses/deepseek-flash:high", "magpie-responses/glm-5.3:max",
                "magpie-responses/glm-5.3-flash:max", "magpie-messages/claude-haiku-5-5:medium",
                "magpie-messages/claude-sonnet-5-5:high", "magpie-messages/claude-opus-5-5:medium",
                "magpie-generative-ai/gemini-4-argon:medium",
            ],
        })
        self.assertEqual(self.render("pi-tiers"), {"tiers": {
            "big": "magpie-responses/gpt-6-astra:max", "medium": "magpie-responses/gpt-6.1-sol:max",
            "small": "magpie-responses/gpt-5.6-sol:max",
        }})
        self.assertEqual(self.render("pi-agent-models"), {
            "Explore": "magpie-responses/gpt-5.6-sol", "Plan": "magpie-responses/gpt-6-astra",
        })

    def test_codex_auth_and_current_identity(self):
        self.assertEqual(self.render("codex"), {
            "model": "gpt-6-astra", "model_provider": "copilotd", "model_reasoning_effort": "xhigh",
            "model_providers": {"copilotd": {
                "name": "copilotd", "base_url": "https://copilotd.ningw.net/openai/v1",
                "wire_api": "responses", "supports_websockets": True,
                "stream_idle_timeout_ms": 600000,
                "auth": {"command": PWSH, "args": [
                    "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                    HOME + "/.config/llm/credentials.ps1", "-Action", "Get", "-Provider", "copilotd",
                ], "timeout_ms": 5000, "refresh_interval_ms": 0},
            }},
        })

    def test_credentials_manifest_only_uses_active_protected_bindings(self):
        self.assertEqual(self.render("credentials"), {
            "schema_version": 1, "providers": {
                "copilotd": {"secret_field": "copilotd_api_key"},
                "magpie": {"secret_field": "magpie_api_key"},
            },
        })
        self.data["harnesses"]["opencode"]["bindings"].append({
            "endpoint": "deepseek.responses", "ids": ["deepseek-flash"],
        })
        self.assertNotIn("deepseek", self.render("credentials")["providers"])
        self.data["harnesses"]["pi"]["bindings"].append({
            "endpoint": "deepseek.responses", "ids": ["deepseek-flash"],
        })
        self.assertEqual(self.render("credentials")["providers"]["deepseek"],
                         {"secret_field": "deepseek_api_key"})
        # Removing the last protected binding removes the credential even though
        # OpenCode still selects the provider.
        self.data["harnesses"]["pi"]["bindings"].pop()
        codex = self.data["harnesses"]["codex"]
        codex["bindings"] = [{"endpoint": "magpie.responses", "ids": ["gpt-6-astra"]}]
        codex["default"]["endpoint"] = "magpie.responses"
        self.assertEqual(set(self.render("credentials")["providers"]), {"magpie"})

    def test_each_harness_selection_is_independent(self):
        pi = self.render("pi-models")
        codex = self.render("codex")
        oc = self.data["harnesses"]["opencode"]
        oc["bindings"] = [{"endpoint": "deepseek.responses", "ids": ["deepseek-flash"]}]
        oc["default"] = {"endpoint": "deepseek.responses", "model": "deepseek-flash"}
        self.assertEqual(self.render("opencode")["model"], "deepseek-responses/deepseek-flash")
        self.assertEqual(self.render("pi-models"), pi)
        self.assertEqual(self.render("codex"), codex)
        self.assertNotIn("deepseek", self.render("credentials")["providers"])

    def test_runtime_identity_and_aliases_follow_all_pi_routes(self):
        binding = self.data["harnesses"]["pi"]["bindings"][0]
        binding["runtime_id"] = "alternate"
        binding["wire_ids"] = {"gpt-6-astra": "group/astra", "gpt-5.6-sol": "group/sol"}
        settings = self.render("pi-settings")
        self.assertEqual(settings["defaultProvider"], "alternate")
        self.assertEqual(settings["defaultModel"], "group/astra")
        self.assertIn("alternate/group/astra:xhigh", settings["enabledModels"])
        self.assertEqual(self.render("pi-tiers")["tiers"]["big"], "alternate/group/astra:max")
        self.assertEqual(self.render("pi-agent-models")["Explore"], "alternate/group/sol")
        self.assertIn("group/astra", [m["id"] for m in self.render("pi-models")["providers"]["alternate"]["models"]])
        self.assertEqual(self.render("opencode")["model"], "magpie-responses/gpt-6-astra")

    def test_opencode_alias_default_and_multiple_codex_responses(self):
        oc = self.data["harnesses"]["opencode"]
        oc["bindings"][0]["wire_ids"] = {"gpt-6-astra": "alias/astra"}
        output = self.render("opencode")
        self.assertEqual(output["model"], "magpie-responses/alias/astra")
        self.assertIn("alias/astra", output["provider"]["magpie-responses"]["models"])
        endpoint = copy.deepcopy(self.data["providers"]["copilotd"]["endpoints"]["responses"])
        endpoint["base_url"] = "https://alternate.example/v1"
        self.data["providers"]["copilotd"]["endpoints"]["alternate"] = endpoint
        codex = self.data["harnesses"]["codex"]
        codex["bindings"].append({"endpoint": "copilotd.alternate", "ids": ["gpt-6-astra"],
                                  "wire_ids": {"gpt-6-astra": "group/astra"}})
        codex["default"]["endpoint"] = "copilotd.alternate"
        output = self.render("codex")
        self.assertEqual(set(output["model_providers"]), {"copilotd", "copilotd-alternate"})
        self.assertEqual(output["model_provider"], "copilotd-alternate")
        self.assertEqual(output["model"], "group/astra")
        self.assertEqual(output["model_providers"]["copilotd-alternate"]["auth"]["args"][-1], "copilotd")

    def test_optional_direct_endpoint_projections(self):
        self.data["harnesses"]["pi"]["bindings"].append({
            "endpoint": "deepseek.responses", "ids": ["deepseek-flash"],
        })
        model = self.render("pi-models")["providers"]["deepseek-responses"]["models"][0]
        self.assertEqual(model["compat"], {"supportsDeveloperRole": False})
        self.data["harnesses"]["opencode"]["bindings"].append({
            "endpoint": "deepseek.messages", "ids": ["deepseek-flash"],
        })
        model = self.render("opencode")["provider"]["deepseek-messages"]["models"]["deepseek-flash"]
        self.assertEqual(model["options"], {"effort": "high", "thinking": {"type": "enabled", "budgetTokens": 0}})

    def test_none_effort_maps_to_pi_off(self):
        default = self.data["harnesses"]["pi"]["default"]
        default.update(model="gpt-6-luna", effort="none")
        self.data["models"]["gpt-6-luna"]["effort"]["default"] = "none"
        settings = self.render("pi-settings")
        self.assertEqual(settings["defaultThinkingLevel"], "off")
        self.assertEqual(settings["enabledModels"][0], "magpie-responses/gpt-6-luna:off")

    def test_encoded_command_keeps_paths_out_of_cmd_and_escapes_powershell(self):
        home = "C:/Users/O'Brien O’Brien O‘Brien $HOME 雪 & ^ %PATH% ! (test)"
        pwsh = "C:/Program Files/O'Brien $ 雪 & (pwsh)/pwsh.exe"
        command = self.render("pi-models", home=home, pwsh=pwsh)["providers"]["magpie-responses"]["apiKey"]
        prefix = '!"' + pwsh + '" -NoLogo -NoProfile -NonInteractive -EncodedCommand '
        self.assertTrue(command.startswith(prefix))
        script = base64.b64decode(command[len(prefix):], validate=True).decode("utf-16le")
        path_data = base64.b64encode((home + "/.config/llm/credentials.ps1").encode("utf-8")).decode("ascii")
        self.assertEqual(script, "& ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
                         + path_data + "'))) -Action Get -Provider 'magpie'")
        self.assertNotIn(home, command)
        auth = self.render("codex", home=home, pwsh=pwsh)["model_providers"]["copilotd"]["auth"]
        self.assertEqual(auth["args"][4], home + "/.config/llm/credentials.ps1")
        self.assertEqual(auth["command"], pwsh)

    @unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_encoded_command_executes_in_windows_cmd_with_synthetic_helper(self):
        # This is an isolated fake HOME and helper. No deployed helper or secrets
        # are read, and cmd.exe (not Bash/PowerShell) is the outer shell.
        with tempfile.TemporaryDirectory(prefix="llm-render-") as temp:
            home = Path(temp) / "O'Brien O’Brien O‘Brien $ 雪 & ^ %PATH% ! (test)"
            helper = home / ".config" / "llm" / "credentials.ps1"
            helper.parent.mkdir(parents=True)
            helper.write_text("param($Action, $Provider)\n[Console]::Out.Write($Action + ':' + $Provider)\n", encoding="utf-8")
            command = self.render("pi-models", home=str(home), pwsh=shutil.which("pwsh"))["providers"]["magpie-responses"]["apiKey"][1:]
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "Get:magpie")

    @unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"), "Windows PowerShell required")
    def test_smart_apostrophe_home_is_data_not_powershell_source(self):
        command = self.render(
            "pi-models", home="C:/Users/O’; Write-Output SYNTHETIC_INJECTION_MARKER; #",
            pwsh=shutil.which("pwsh"),
        )["providers"]["magpie-responses"]["apiKey"][1:]
        # The nonexistent literal helper path must fail; no injected command runs.
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("SYNTHETIC_INJECTION_MARKER", result.stdout)

    def test_deterministic_read_only_render_and_independent_outputs(self):
        before = copy.deepcopy(self.data)
        with patch.object(Path, "open", side_effect=AssertionError("render must not read files")), \
             patch.object(subprocess, "run", side_effect=AssertionError("render must not execute commands")):
            for target in renderer.TARGETS:
                self.assertEqual(self.render(target), self.render(target))
        result = self.render("pi-models")
        result["providers"]["magpie-messages"]["models"][0]["cost"]["tiers"][0]["input"] = 999
        self.assertEqual(self.data, before)

    def test_invalid_shapes_and_unknown_fields_rejected_without_values(self):
        sentinel = "DO_NOT_ECHO_CREDENTIAL_SENTINEL"
        cases = [
            ((), sentinel, True), (("providers", "deepseek"), sentinel, True),
            (("providers", "deepseek", "credential"), sentinel, True),
            (("providers", "deepseek", "endpoints", "responses"), sentinel, True),
            (("models", "gpt-6-astra"), sentinel, True),
            (("models", "gpt-6-astra", "effort"), sentinel, True),
            (("models", "gpt-6-astra", "cost"), sentinel, True),
            (("models", "gpt-6-astra", "cost", "tiers", 0), sentinel, True),
            (("harnesses",), sentinel, True), (("harnesses", "pi"), sentinel, True),
            (("harnesses", "pi", "bindings", 0), sentinel, True),
            (("harnesses", "pi", "default"), sentinel, True),
            (("harnesses", "pi", "workflow_tiers", "big"), sentinel, True),
            (("harnesses", "pi", "agent_models", "Plan"), sentinel, True),
        ]
        for path, key, value in cases:
            with self.subTest(path=path):
                self.data = copy.deepcopy(self.original)
                node = self.data
                for part in path:
                    node = node[part]
                node[key] = value
                with self.assertRaises(renderer.ConfigError) as error:
                    self.render("credentials")
                self.assertNotIn(sentinel, str(error.exception))

    def test_invalid_values_rejected(self):
        # All inventory entries are checked, including unused DeepSeek routes.
        endpoint = ("providers", "deepseek", "endpoints", "responses")
        model = ("models", "gpt-6-astra")
        binding = ("harnesses", "pi", "bindings", 0)
        cases = [
            (("providers",), {}), (("models",), []), (("harnesses",), {}),
            (endpoint + ("contract",), "unknown"), (endpoint + ("contract",), []),
            (endpoint + ("base_url",), "https://user:DO_NOT_ECHO@example.com/v1"),
            (endpoint + ("base_url",), "https://example.com/v1?api_key=DO_NOT_ECHO"),
            (endpoint + ("base_url",), "https://example.com/v1#DO_NOT_ECHO"),
            (endpoint + ("base_url",), "https://example.com/v1/"),
            (endpoint + ("base_url",), "https://example.com:invalid/v1"),
            (endpoint + ("base_url",), "https:///v1"),
            (endpoint + ("base_url",), "https://example.com\\@elsewhere/v1"),
            (endpoint + ("base_url",), "https://example.com/%40secret"),
            (endpoint + ("base_url",), "file:///v1"),
            (endpoint + ("supports_websockets",), 1),
            (("providers", "deepseek", "credential", "env"), "bad-env"),
            (("providers", "deepseek", "credential", "secret_field"), ""),
            (model + ("context_window",), True), (model + ("max_output",), 1.5),
            (model + ("max_output",), 0), (model + ("thinking",), 1),
            (model + ("vision",), "yes"), (model + ("temperature",), 0),
            (model + ("effort", "levels"), []),
            (model + ("effort", "levels"), ["high", "high"]),
            (model + ("effort", "levels"), ["ultra"]),
            (model + ("effort", "default"), "none"),
            (model + ("cost", "input"), True), (model + ("cost", "input"), -1),
            (model + ("cost", "input"), float("inf")),
            (model + ("cost", "input"), float("nan")),
            (model + ("cost", "tiers", 0, "input_tokens_above"), True),
            (model + ("cost", "tiers", 0, "input"), "1"),
            (binding + ("endpoint",), "missing.responses"),
            (binding + ("endpoint",), "magpie.missing"),
            (binding + ("ids",), ["unknown"]), (binding + ("ids",), []),
            (binding + ("ids",), ["gpt-6-astra", "gpt-6-astra"]),
            (binding + ("ids",), [""]), (binding + ("ids",), [True]),
            (binding + ("runtime_id",), ""), (binding + ("runtime_id",), "bad/id"),
            (binding + ("wire_ids",), {"unselected": "alias"}),
            (binding + ("wire_ids",), {"gpt-6-astra": ""}),
            (binding + ("wire_ids",), {"gpt-6-astra": "alias:high"}),
            (binding + ("wire_ids",), {"gpt-6-astra": "../alias"}),
            (binding + ("wire_ids",), {"gpt-6-astra": "gpt-5.6-sol"}),
            (("harnesses", "codex", "stream_idle_timeout_ms"), True),
            (("harnesses", "pi", "default", "endpoint"), "copilotd.responses"),
            (("harnesses", "pi", "default", "model"), "claude-opus-5-5"),
            (("harnesses", "pi", "default", "effort"), "none"),
            (("harnesses", "pi", "workflow_tiers", "big", "effort"), "ultra"),
            (("harnesses", "pi", "agent_models", "Explore", "model"), "missing"),
        ]
        for path, value in cases:
            with self.subTest(path=path, value=value):
                self.data = copy.deepcopy(self.original)
                node = self.data
                for part in path[:-1]:
                    node = node[part]
                node[path[-1]] = value
                with self.assertRaises(renderer.ConfigError) as error:
                    self.render("credentials")
                self.assertNotIn("DO_NOT_ECHO", str(error.exception))

    def test_missing_fields_collisions_and_invalid_contract_combinations(self):
        for harness in ("pi", "opencode", "codex"):
            with self.subTest(harness=harness):
                self.data = copy.deepcopy(self.original)
                del self.data["harnesses"][harness]["default"]
                with self.assertRaises(renderer.ConfigError):
                    self.render("credentials")
        self.data = copy.deepcopy(self.original)
        bindings = self.data["harnesses"]["pi"]["bindings"]
        bindings.append(copy.deepcopy(bindings[0]))
        with self.assertRaisesRegex(renderer.ConfigError, "duplicate"):
            self.render("pi-models")
        bindings.pop()
        bindings[0]["runtime_id"] = "magpie-messages"
        with self.assertRaisesRegex(renderer.ConfigError, "duplicate"):
            self.render("pi-models")
        for harness, endpoint, ids in (
            ("pi", "deepseek.messages", ["deepseek-flash"]),
            ("codex", "magpie.messages", ["claude-opus-5-5"]),
            ("opencode", "magpie.generative-ai", ["gpt-6-astra"]),
        ):
            with self.subTest(harness=harness, endpoint=endpoint):
                self.data = copy.deepcopy(self.original)
                self.data["harnesses"][harness]["bindings"][0] = {"endpoint": endpoint, "ids": ids}
                with self.assertRaises(renderer.ConfigError):
                    self.render("credentials")
        self.data = copy.deepcopy(self.original)
        cost = self.data["models"]["gpt-6-astra"]["cost"]
        cost["tiers"].append(copy.deepcopy(cost["tiers"][0]))
        with self.assertRaisesRegex(renderer.ConfigError, "increasing"):
            self.render("pi-models")

    def test_manifest_ownership_and_fixed_pi_route_keys(self):
        for provider_id in ("Magpie", "1magpie", "a" * 65, "", "bad.name"):
            with self.subTest(provider_id=provider_id):
                self.data = copy.deepcopy(self.original)
                self.data["providers"][provider_id] = self.data["providers"].pop("deepseek")
                with self.assertRaises(renderer.ConfigError):
                    self.render("credentials")
        for field in ("Uppercase", "1field", "a" * 129, "bad-field", ""):
            with self.subTest(field=field):
                self.data = copy.deepcopy(self.original)
                self.data["providers"]["deepseek"]["credential"]["secret_field"] = field
                with self.assertRaises(renderer.ConfigError):
                    self.render("credentials")
        for key, value in (("secret_field", "magpie_api_key"), ("env", "MAGPIE_API_KEY"),
                           ("env", "magpie_api_key")):
            with self.subTest(key=key, value=value):
                self.data = copy.deepcopy(self.original)
                self.data["providers"]["deepseek"]["credential"][key] = value
                with self.assertRaisesRegex(renderer.ConfigError, "ownership"):
                    self.render("credentials")
        for field, key in (("agent_models", "Plan"), ("workflow_tiers", "small")):
            for change in ("missing", "extra"):
                with self.subTest(field=field, change=change):
                    self.data = copy.deepcopy(self.original)
                    routes = self.data["harnesses"]["pi"][field]
                    if change == "missing":
                        del routes[key]
                    else:
                        routes["unexpected"] = copy.deepcopy(routes[key])
                    with self.assertRaises(renderer.ConfigError):
                        self.render("credentials")

    def test_invalid_target_and_paths(self):
        for target in ("unknown", None, []):
            with self.subTest(target=target), self.assertRaises(renderer.ConfigError):
                self.render(target)
        for home, pwsh in (
            ("relative", PWSH), (HOME, "pwsh"), (HOME, "C:pwsh.exe"),
            (HOME, "C:/%PATH%/pwsh.exe"), (HOME, "C:/!unsafe!/pwsh.exe"),
            (HOME, 'C:/unsafe"/pwsh.exe'), (HOME + "\n", PWSH),
            (HOME, "C:/Windows/cmd.exe"),
        ):
            with self.subTest(home=home, pwsh=pwsh), self.assertRaises(renderer.ConfigError):
                self.render("pi-models", home=home, pwsh=pwsh)

    def test_loader_rejects_malformed_duplicate_and_wrong_namespace_toml(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / ".chezmoidata"
            directory.mkdir()
            for name in ("providers", "models", "harnesses"):
                shutil.copyfile(ROOT / ".chezmoidata" / f"llm-{name}.toml", directory / f"llm-{name}.toml")
            self.assertEqual(renderer.load_data(root), self.original)
            file = directory / "llm-providers.toml"
            original = file.read_text(encoding="utf-8")
            for content in ("broken = [DO_NOT_ECHO", original + "\n[llm.providers.magpie]\n",
                            "[wrong.providers]\n", original + "\n[llm.models]\n"):
                file.write_text(content, encoding="utf-8")
                with self.assertRaises(renderer.ConfigError) as error:
                    renderer.load_data(root)
                self.assertNotIn("DO_NOT_ECHO", str(error.exception))
            file.unlink()
            with self.assertRaises(renderer.ConfigError):
                renderer.load_data(root)

    def test_cli_pretty_json_and_nonsecret_errors(self):
        command = [sys.executable, "-B", str(ROOT / "render_llm_config.py"), "credentials",
                   "--source", str(ROOT), "--home", HOME, "--pwsh", PWSH]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), self.render("credentials"))
        self.assertIn('\n  "providers": {', result.stdout)
        command[3] = "DO_NOT_ECHO_CREDENTIAL_SENTINEL"
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("unknown projection target", result.stderr)
        self.assertNotIn("DO_NOT_ECHO", result.stderr)
        result = subprocess.run(command + ["--DO_NOT_ECHO"], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("DO_NOT_ECHO", result.stderr)


if __name__ == "__main__":
    unittest.main()
