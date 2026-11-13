#!/usr/bin/env python3
"""Read-only LLM projections. Python 3.11+, standard library only.

load_data(source_dir) reads exactly .chezmoidata/llm-{providers,models,harnesses}.toml
and returns their merged *llm contents*: {providers, models, harnesses}.
render(data, target, home, pwsh) validates all data, then returns one JSON object.
Neither function reads credentials, invokes commands, nor writes deployed files.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import re
import sys
import tomllib
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit


TARGETS = (
    "pi-models", "pi-settings", "pi-tiers", "pi-agent-models",
    "opencode", "codex", "credentials",
)
CONTRACTS = {
    "openai-responses", "anthropic-messages", "google-generative-ai",
}
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
PACKAGES = {
    "openai-responses": "@ai-sdk/openai",
    "anthropic-messages": "@ai-sdk/anthropic",
    "google-generative-ai": "@ai-sdk/google",
}
ID = r"[A-Za-z0-9][A-Za-z0-9_-]*"
PROVIDER_ID = r"[a-z][a-z0-9_-]{0,63}"
SECRET_FIELD = r"[a-z][a-z0-9_]{0,127}"
MODEL_ID = r"[A-Za-z0-9][A-Za-z0-9._-]*"
WIRE_ID = r"[A-Za-z0-9][A-Za-z0-9._/-]*"
VARIABLE = r"[A-Za-z_][A-Za-z0-9_]*"


class ConfigError(ValueError):
    """A nonsecret diagnostic: messages never interpolate input values."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def _object(value: object, required: set[str], optional: set[str], where: str) -> None:
    _require(type(value) is dict, f"{where}: expected a table")
    _require(required <= value.keys(), f"{where}: missing required fields")
    _require(value.keys() <= required | optional, f"{where}: unknown fields")


def _text(value: object, where: str, pattern: str | None = None) -> None:
    _require(isinstance(value, str) and bool(value.strip()), f"{where}: expected nonempty text")
    _require(not any(ord(c) < 32 or ord(c) == 127 for c in value), f"{where}: control characters forbidden")
    if pattern:
        _require(re.fullmatch(pattern, value) is not None, f"{where}: invalid identifier")


def _table(value: object, where: str, pattern: str = ID) -> None:
    _require(type(value) is dict and bool(value), f"{where}: expected a nonempty table")
    for key in value:
        _text(key, where, pattern)


def _integer(value: object, where: str) -> None:
    _require(type(value) is int and value > 0, f"{where}: expected a positive integer")


def _boolean(value: object, where: str) -> None:
    _require(type(value) is bool, f"{where}: expected a boolean")


def _strings(value: object, where: str, pattern: str = MODEL_ID) -> None:
    _require(type(value) is list and bool(value), f"{where}: expected a nonempty list")
    for item in value:
        _text(item, where, pattern)
    _require(len(value) == len(set(value)), f"{where}: duplicate IDs")


def _url(value: object) -> None:
    _text(value, "endpoint.base_url")
    _require(not any(c.isspace() for c in value) and not any(c in value for c in "\\%?#"),
             "endpoint.base_url: invalid URL or credential-bearing URL")
    try:
        parts = urlsplit(value)
        port = parts.port
        hostname = parts.hostname
    except ValueError:
        raise ConfigError("endpoint.base_url: invalid URL") from None
    _require(parts.scheme in {"http", "https"} and bool(hostname) and bool(parts.netloc),
             "endpoint.base_url: expected absolute HTTP(S) URL")
    _require(parts.username is None and parts.password is None and "@" not in parts.netloc,
             "endpoint.base_url: credentials in URL forbidden")
    _require(not value.endswith("/") and (port is None or port > 0),
             "endpoint.base_url: invalid port or trailing slash")
    _require(re.fullmatch(r"[A-Za-z0-9.:\[\]-]+", hostname) is not None,
             "endpoint.base_url: invalid hostname")
    _require(re.fullmatch(r"[/A-Za-z0-9._~-]*", parts.path) is not None,
             "endpoint.base_url: invalid SDK prefix")


def _providers(providers: object) -> None:
    _table(providers, "providers", PROVIDER_ID)
    secret_fields, environments = set(), set()
    for provider in providers.values():
        _object(provider, {"name", "credential", "endpoints"}, set(), "provider")
        _text(provider["name"], "provider.name")
        credential = provider["credential"]
        _object(credential, {"secret_field", "env"}, set(), "provider.credential")
        _text(credential["secret_field"], "provider.credential.secret_field", SECRET_FIELD)
        _text(credential["env"], "provider.credential.env", VARIABLE)
        # Distinct provider identities cannot accidentally claim the same secret.
        # Windows environment names are case-insensitive.
        env = credential["env"].upper()
        _require(credential["secret_field"] not in secret_fields and env not in environments,
                 "provider.credential: duplicate credential ownership")
        secret_fields.add(credential["secret_field"])
        environments.add(env)
        _table(provider["endpoints"], "provider.endpoints")
        for endpoint in provider["endpoints"].values():
            _object(endpoint, {"name", "contract", "base_url"},
                    {"supports_websockets", "supports_developer_role", "thinking_type"}, "endpoint")
            _text(endpoint["name"], "endpoint.name")
            _text(endpoint["contract"], "endpoint.contract")
            _require(endpoint["contract"] in CONTRACTS, "endpoint: unsupported contract")
            _url(endpoint["base_url"])
            for field in ("supports_websockets", "supports_developer_role"):
                if field in endpoint:
                    _boolean(endpoint[field], "endpoint capabilities")
                    _require(endpoint["contract"] == "openai-responses",
                             "endpoint: Responses capability requires Responses contract")
            if "thinking_type" in endpoint:
                _require(endpoint["thinking_type"] == "enabled" and
                         endpoint["contract"] == "anthropic-messages",
                         "endpoint: thinking_type requires enabled Messages thinking")


def _cost(cost: object) -> None:
    fields = {"input", "output", "cache_read", "cache_write"}
    _object(cost, fields, {"tiers"}, "model.cost")

    def rates(value: dict) -> None:
        for field in fields:
            number = value[field]
            _require(type(number) in (int, float), "model.cost: expected numeric rates")
            # isfinite() on an arbitrary-precision integer can overflow.
            _require(number >= 0 and (type(number) is int or math.isfinite(number)),
                     "model.cost: rates must be finite and nonnegative")

    rates(cost)
    if "tiers" in cost:
        _require(type(cost["tiers"]) is list and bool(cost["tiers"]),
                 "model.cost.tiers: expected a nonempty list")
        previous = 0
        for tier in cost["tiers"]:
            _object(tier, fields | {"input_tokens_above"}, set(), "model.cost.tier")
            _integer(tier["input_tokens_above"], "model.cost.tier threshold")
            _require(tier["input_tokens_above"] > previous,
                     "model.cost.tiers: thresholds must be strictly increasing")
            previous = tier["input_tokens_above"]
            rates(tier)


def _models(models: object) -> None:
    _table(models, "models", MODEL_ID)
    for model in models.values():
        _object(model, {"name", "context_window", "max_output", "thinking", "vision", "effort", "cost"},
                {"temperature"}, "model")
        _text(model["name"], "model.name")
        for field in ("context_window", "max_output"):
            _integer(model[field], "model token limits")
        for field in ("thinking", "vision", "temperature"):
            if field in model:
                _boolean(model[field], "model capabilities")
        _cost(model["cost"])
        effort = model["effort"]
        _object(effort, {"levels", "default"}, set(), "model.effort")
        _strings(effort["levels"], "model.effort.levels")
        _text(effort["default"], "model.effort.default")
        _require(set(effort["levels"]) <= EFFORTS, "model.effort: unsupported effort")
        _require(effort["default"] in effort["levels"], "model.effort: default not supported")
        _require(model["thinking"] or effort["levels"] == ["none"],
                 "model.effort: nonthinking models require none-only effort")


def _binding(data: dict, binding: object, harness: str) -> dict:
    _object(binding, {"endpoint", "ids"}, {"runtime_id", "wire_ids"}, "binding")
    _text(binding["endpoint"], "binding.endpoint", ID + r"\." + ID)
    provider_id, endpoint_id = binding["endpoint"].split(".")
    _require(provider_id in data["providers"], "binding: unknown provider")
    provider = data["providers"][provider_id]
    _require(endpoint_id in provider["endpoints"], "binding: unknown endpoint")
    endpoint = provider["endpoints"][endpoint_id]
    _require(harness != "codex" or endpoint["contract"] == "openai-responses",
             "codex binding: only Responses endpoints supported")
    _require(harness != "pi" or "thinking_type" not in endpoint,
             "pi binding: enabled Messages thinking unsupported")
    runtime_id = binding.get("runtime_id", f"{provider_id}-{endpoint_id}")
    _text(runtime_id, "binding.runtime_id", MODEL_ID)
    _strings(binding["ids"], "binding.ids")
    _require(set(binding["ids"]) <= data["models"].keys(), "binding: unknown catalog model")
    aliases = binding.get("wire_ids", {})
    _object(aliases, set(), set(binding["ids"]), "binding.wire_ids")
    for value in aliases.values():
        _text(value, "binding.wire_ids", WIRE_ID)
        _require(not value.endswith("/") and "//" not in value and
                 not any(p in {".", ".."} for p in value.split("/")),
                 "binding.wire_ids: invalid alias")
    wire_ids = {key: aliases.get(key, key) for key in binding["ids"]}
    _require(len(wire_ids) == len(set(wire_ids.values())), "binding: duplicate wire IDs")
    for key in binding["ids"]:
        levels = set(data["models"][key]["effort"]["levels"])
        if endpoint["contract"] == "google-generative-ai":
            _require(levels <= {"low", "medium", "high"}, "binding: unsupported Google effort")
        if endpoint["contract"] == "anthropic-messages":
            supported = {"none", "low", "medium", "high", "xhigh", "max"}
            if "thinking_type" in endpoint:
                supported = {"none", "low", "high", "max"}
            _require(levels <= supported, "binding: unsupported Messages effort")
    return {"reference": binding["endpoint"], "runtime_id": runtime_id,
            "provider_id": provider_id, "provider": provider, "endpoint": endpoint,
            "wire_ids": wire_ids}


def _route(route: object, bindings: list[dict], models: dict, effort: bool) -> tuple[dict, str]:
    _object(route, {"endpoint", "model"} | ({"effort"} if effort else set()), set(), "route")
    _text(route["endpoint"], "route.endpoint", ID + r"\." + ID)
    _text(route["model"], "route.model", MODEL_ID)
    binding = next((b for b in bindings if b["reference"] == route["endpoint"]), None)
    _require(binding is not None, "route: endpoint not bound in this harness")
    _require(route["model"] in binding["wire_ids"], "route: model not bound in this harness")
    if effort:
        _text(route["effort"], "route.effort")
        _require(route["effort"] in models[route["model"]]["effort"]["levels"],
                 "route: unsupported effort for selected model")
    return binding, binding["wire_ids"][route["model"]]


def _validate(data: object) -> dict[str, list[dict]]:
    _object(data, {"providers", "models", "harnesses"}, set(), "llm")
    _providers(data["providers"])
    _models(data["models"])
    _object(data["harnesses"], {"pi", "opencode", "codex"}, set(), "harnesses")
    resolved = {}
    for name, harness in data["harnesses"].items():
        extra = {"workflow_tiers", "agent_models"} if name == "pi" else set()
        if name == "codex":
            extra = {"stream_idle_timeout_ms"}
        _object(harness, {"bindings", "default"} | extra, set(), "harness")
        _require(type(harness["bindings"]) is list and bool(harness["bindings"]),
                 "harness.bindings: expected a nonempty list")
        bindings = [_binding(data, binding, name) for binding in harness["bindings"]]
        for field in ("reference", "runtime_id"):
            _require(len(bindings) == len({b[field] for b in bindings}),
                     "harness.bindings: duplicate endpoint or runtime identity")
        _route(harness["default"], bindings, data["models"], effort=name != "opencode")
        if name == "codex":
            _integer(harness["stream_idle_timeout_ms"], "codex.stream_idle_timeout_ms")
        if name == "pi":
            for field, keys in (("workflow_tiers", {"big", "medium", "small"}),
                                ("agent_models", {"Explore", "Plan"})):
                _object(harness[field], keys, set(), "pi routes")
                for route in harness[field].values():
                    _route(route, bindings, data["models"], effort=field == "workflow_tiers")
        resolved[name] = bindings
    return resolved


def load_data(source_dir: Path) -> dict:
    """Load only the three declarative inputs, validate, and return llm contents."""
    data = {}
    for section in ("providers", "models", "harnesses"):
        path = source_dir / ".chezmoidata" / f"llm-{section}.toml"
        try:
            with path.open("rb") as source:
                parsed = tomllib.load(source)
        except (OSError, ValueError):
            raise ConfigError(f"llm-{section}.toml: unable to read valid TOML") from None
        _object(parsed, {"llm"}, set(), "data file")
        _object(parsed["llm"], {section}, set(), "data file llm namespace")
        data[section] = parsed["llm"][section]
    _validate(data)
    return data


def _paths(home: object, pwsh: object) -> tuple[str, str]:
    for value, where in ((home, "home"), (pwsh, "pwsh")):
        _text(value, where)
        _require(PureWindowsPath(value).is_absolute(), f"{where}: expected an absolute Windows path")
        _require('"' not in value, f"{where}: quotes forbidden in Windows path")
    # cmd.exe expands percent/delayed-expansion variables even inside quotes.
    # HOME never appears in cmd: it is entirely inside the encoded PS script.
    _require(not any(c in pwsh for c in '%!'), "pwsh: shell expansion characters forbidden")
    _require(PureWindowsPath(pwsh).name.lower() == "pwsh.exe", "pwsh: expected pwsh.exe")
    return home.replace("\\", "/").rstrip("/") + "/.config/llm/credentials.ps1", pwsh


def _pi_key(helper: str, pwsh: str, provider_id: str) -> str:
    # Treat paths as data. PowerShell recognizes smart apostrophes as delimiters
    # too, so escaping only ASCII apostrophes before encoding a script is unsafe.
    helper_data = base64.b64encode(helper.encode("utf-8")).decode("ascii")
    script = ("& ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
              + helper_data + "'))) -Action Get -Provider '" + provider_id + "'")
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    # Pi executes !commands through child_process.exec's Windows cmd shell.
    # Only the quoted executable and inert base64 reach that shell.
    return f'!"{pwsh}" -NoLogo -NoProfile -NonInteractive -EncodedCommand {encoded}'


def _pi_level(effort: str) -> str:
    return "off" if effort == "none" else effort


def _route_string(route: dict, bindings: list[dict], models: dict, effort: bool = False) -> str:
    binding, wire_id = _route(route, bindings, models, effort)
    result = f'{binding["runtime_id"]}/{wire_id}'
    return result + ":" + _pi_level(route["effort"]) if effort else result


def _pi_model(model: dict, endpoint: dict, wire_id: str) -> dict:
    levels = model["effort"]["levels"]
    thinking = {"off": "none" if "none" in levels else None,
                "minimal": "minimal" if "minimal" in levels else None}
    thinking.update({level: None for level in ("low", "medium", "high") if level not in levels})
    thinking.update({level: level for level in ("xhigh", "max") if level in levels})
    renames = {"cache_read": "cacheRead", "cache_write": "cacheWrite", "input_tokens_above": "inputTokensAbove"}
    cost = {renames.get(k, k): v for k, v in model["cost"].items() if k != "tiers"}
    if "tiers" in model["cost"]:
        cost["tiers"] = [{renames.get(k, k): v for k, v in t.items()} for t in model["cost"]["tiers"]]
    result = {"id": wire_id, "name": model["name"], "contextWindow": model["context_window"],
              "maxTokens": model["max_output"], "reasoning": model["thinking"],
              "input": ["text", "image"] if model["vision"] else ["text"],
              "cost": cost, "thinkingLevelMap": thinking}
    compat = {}
    if endpoint["contract"] == "anthropic-messages":
        compat["forceAdaptiveThinking"] = True
        if "temperature" in model:
            compat["supportsTemperature"] = model["temperature"]
    if "supports_developer_role" in endpoint:
        compat["supportsDeveloperRole"] = endpoint["supports_developer_role"]
    if compat:
        result["compat"] = compat
    return result


def _opencode_effort(endpoint: dict, effort: str) -> dict:
    if endpoint["contract"] == "google-generative-ai":
        return {"thinkingConfig": {"includeThoughts": True, "thinkingLevel": effort}}
    if endpoint["contract"] == "anthropic-messages":
        if effort == "none":
            return {"thinking": {"type": "disabled"}}
        thinking = {"type": "adaptive"}
        if "thinking_type" in endpoint:
            thinking = {"type": "enabled", "budgetTokens": 0}
        return {"effort": effort, "thinking": thinking}
    return {"reasoningEffort": effort}


def _opencode_model(model: dict, endpoint: dict) -> dict:
    result = {"name": model["name"], "reasoning": model["thinking"],
              "modalities": {"input": ["text", "image"] if model["vision"] else ["text"], "output": ["text"]},
              "limit": {"context": model["context_window"], "output": model["max_output"]},
              # V1 cannot label arbitrary thresholds such as 100k or 272k.
              "cost": {k: v for k, v in model["cost"].items() if k != "tiers"},
              "variants": {e: _opencode_effort(endpoint, e) for e in model["effort"]["levels"]},
              "options": _opencode_effort(endpoint, model["effort"]["default"])}
    if "temperature" in model:
        result["temperature"] = model["temperature"]
    return result


def render(data: dict, target: str, home: str, pwsh: str) -> dict:
    """Validate all inputs and render a reusable projection without side effects."""
    _require(isinstance(target, str) and target in TARGETS, "unknown projection target")
    bindings = _validate(data)
    helper, pwsh = _paths(home, pwsh)
    models, harnesses = data["models"], data["harnesses"]
    if target == "credentials":
        active = {b["provider_id"] for h in ("pi", "codex") for b in bindings[h]}
        return {"schema_version": 1, "providers": {
            key: {"secret_field": data["providers"][key]["credential"]["secret_field"]}
            for key in sorted(active)}}
    if target == "pi-models":
        return {"providers": {b["runtime_id"]: {
            "api": b["endpoint"]["contract"], "baseUrl": b["endpoint"]["base_url"],
            "apiKey": _pi_key(helper, pwsh, b["provider_id"]),
            "models": [_pi_model(models[key], b["endpoint"], wire) for key, wire in b["wire_ids"].items()],
        } for b in bindings["pi"]}}
    if target == "pi-settings":
        default = harnesses["pi"]["default"]
        binding, wire_id = _route(default, bindings["pi"], models, effort=True)
        return {"defaultProvider": binding["runtime_id"], "defaultModel": wire_id,
                "defaultThinkingLevel": _pi_level(default["effort"]),
                "enabledModels": [f'{b["runtime_id"]}/{wire}:{_pi_level(models[key]["effort"]["default"])}'
                                  for b in bindings["pi"] for key, wire in b["wire_ids"].items()]}
    if target in {"pi-tiers", "pi-agent-models"}:
        tiers = target == "pi-tiers"
        field = "workflow_tiers" if tiers else "agent_models"
        result = {key: _route_string(route, bindings["pi"], models, effort=tiers)
                  for key, route in harnesses["pi"][field].items()}
        return {"tiers": result} if tiers else result
    if target == "opencode":
        providers = {}
        for binding in bindings["opencode"]:
            endpoint = binding["endpoint"]
            providers[binding["runtime_id"]] = {
                "name": endpoint["name"], "npm": PACKAGES[endpoint["contract"]],
                "options": {
                    "baseURL": endpoint["base_url"] + ("/v1" if endpoint["contract"] == "anthropic-messages" else ""),
                    "apiKey": "{env:" + binding["provider"]["credential"]["env"] + "}",
                },
                "models": {wire: _opencode_model(models[key], endpoint) for key, wire in binding["wire_ids"].items()},
            }
        return {"provider": providers, "enabled_providers": sorted(providers),
                "model": _route_string(harnesses["opencode"]["default"], bindings["opencode"], models)}
    # Codex may register several independent Responses endpoints. Its active
    # default, like every other route, resolves through that harness's bindings.
    default = harnesses["codex"]["default"]
    binding, wire_id = _route(default, bindings["codex"], models, effort=True)
    providers = {}
    for b in bindings["codex"]:
        endpoint = b["endpoint"]
        provider = {"name": b["provider"]["name"], "base_url": endpoint["base_url"],
                    "wire_api": "responses", "stream_idle_timeout_ms": harnesses["codex"]["stream_idle_timeout_ms"],
                    "auth": {"command": pwsh,
                             "args": ["-NoLogo", "-NoProfile", "-NonInteractive", "-File", helper,
                                      "-Action", "Get", "-Provider", b["provider_id"]],
                             "timeout_ms": 5000, "refresh_interval_ms": 0}}
        if "supports_websockets" in endpoint:
            provider["supports_websockets"] = endpoint["supports_websockets"]
        providers[b["runtime_id"]] = provider
    return {"model": wire_id, "model_provider": binding["runtime_id"],
            "model_reasoning_effort": default["effort"], "model_providers": providers}


def main(argv: list[str] | None = None) -> int:
    # Avoid argparse's default errors, which echo arbitrary user-supplied values.
    class Parser(argparse.ArgumentParser):
        def error(self, message: str) -> None:
            raise ConfigError("expected TARGET --source DIR --home HOME --pwsh ABSOLUTE_PWSH")

    parser = Parser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--home", required=True)
    parser.add_argument("--pwsh", required=True)
    try:
        args = parser.parse_args(argv)
        result = render(load_data(args.source), args.target, args.home, args.pwsh)
        output = json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False, sort_keys=True)
    except ConfigError as error:
        print(f"LLM configuration error: {error}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError):
        print("LLM configuration error: invalid input or unavailable source", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
