# LLM configuration and protected credentials

Chezmoi owns initialization and subsequent updates. Edit source declarations or
`secrets.yaml.age`, preview with `chezmoi diff`, then deploy with `chezmoi apply`.
There is no separate generation, seeding command, service, or background sync.
Agent-driven applies must use `--force` because Pi also rewrites its settings.

## Ownership and declarations

- `.chezmoidata/llm-providers.toml`: inference operators, credential references,
  named endpoints, protocol contracts, and endpoint compatibility facts.
- `.chezmoidata/llm-models.toml`: route-independent model metadata, reasoning
  ladders/defaults, limits, and display pricing. Gateway aliases are not models.
- `.chezmoidata/llm-harnesses.toml`: explicit per-harness endpoint/model bindings,
  optional wire aliases, defaults, and Pi's workflow/subagent model selections.
- `render_llm_config.py`: validates these declarations and returns deterministic
  client-specific JSON projections. It never decrypts, fetches, or writes files.
- `.chezmoitemplates/llm/`: thin rendering glue and non-inference configuration.
  Chezmoi templates compose the projections into the managed client files.
- `dot_config/llm/credentials.ps1`: the Windows adapter that publishes and reads
  one CurrentUser-DPAPI-protected snapshot under `~/.config/llm/store/`.
- `.chezmoiscripts/run_before_llm-credentials.ps1.tmpl`: invokes publication during
  apply, using the source helper so a fresh home does not need deployed helpers.

A provider can own multiple endpoints. An endpoint describes a protocol, not a
model family. Multiple harnesses can bind the same endpoint; a model can be
bound on multiple endpoints with different request IDs. Registration, default
selection, and Pi model cycling are separate projections. Pi `enabledModels`
controls cycling, not a strict `/model` picker allowlist.

Codex's historical runtime provider ID remains `copilotd`; its binding refers to
the registry's Responses endpoint. The old machine-local `data.codex_provider`
choice is obsolete: versioned bindings are now authoritative. An existing saved
value is ignored and can be removed with `chezmoi edit-config`; reinitialization
no longer prompts for it.

For example, the provider registry declares `[llm.providers.magpie.endpoints.responses]`
with its contract and URL. A harness independently selects it:

```toml
[[llm.harnesses.pi.bindings]]
endpoint = "magpie.responses"
ids = ["gpt-6-astra", "deepseek-flash"]
# Optional, scoped to this binding only:
# wire_ids = { "gpt-6-astra" = "gateway/astra" }
```

Defaults and task selections use catalog IDs, so a wire alias automatically
reaches those routes. The neutral model lives under `[llm.models."gpt-6-astra"]`.
Adding a binding for another harness does not copy that model definition.

The renderer rejects invalid references, duplicate registrations/aliases,
unsupported contracts, and defaults/task routes outside selected bindings.
Client-specific translations live in the renderer, including OpenCode's
Anthropic `/v1` prefix and Pi reasoning-level suppression. Model display costs
are metadata; provider billing remains authoritative. Updating a catalog entry
does not establish account entitlement to that model.

## Protected provider credentials

Keep the existing flat encrypted fields:

| Provider | Required field when selected by Codex/Pi |
| --- | --- |
| Copilotd | `copilotd_api_key` |
| Magpie | `magpie_api_key` |

Only providers bound by the protected clients enter the snapshot. Merely adding
a provider to the registry does not require its credential. Missing or empty
required fields fail publication; there is no ambient environment or legacy-name
fallback. Remove the binding to retire an unused credential. Publication
replaces the whole owned snapshot rather than merging old entries forever.

During apply, the hook captures a fixed chezmoi extraction template's selected
secret values through a subprocess pipe. They do not appear in rendered hook
text, command arguments, or plaintext temporary files. Child template execution
uses isolated state/cache to avoid contending with the parent apply. The helper
validates the input and writes only Windows CurrentUser-protected ciphertext.
Its owned directory has a restricted Windows ACL; unexpected ownership,
reparse points, or malformed state fail closed.

Runtime retrieval does not need age, the source checkout, Python, or a shell
profile:

- **Codex CLI and native Windows Codex Desktop** share the credential command in
  `~/.codex/config.toml`. The helper prints the selected token to a captured pipe.
- **Pi** uses `models.json` credential commands for all three Magpie endpoints.
  They refer to the same provider credential, not three secret copies.

The hook runs on normal applies so a deleted derived store can be rebuilt.
Unchanged credentials leave its ciphertext unchanged. Rotation updates the
snapshot; removing a provider binding drops its stored key. A failed operation
before replacement preserves the previous snapshot. Chezmoi's overall apply is
not a transaction: a later, unrelated hook failure does not roll back an already
published store. Fix the failure and reapply. A crash that leaves an unexpected
staging file, corrupt snapshot, or unsafe ACL fails closed instead of being
automatically adopted or repaired. With publishers stopped, inspect and remove
only this derived `~/.config/llm/store/` directory, then reapply to rebuild it from
age; never delete native login stores or the source ciphertext. Targeted applies
or skipped scripts may omit publication; use a normal apply for credential changes.

Python 3.11+ must be provisioned before rendering; PowerShell 7 must be installed
before publication/runtime retrieval. Defaults use Scoop's Python and
`C:/Program Files/PowerShell/7/pwsh.exe`. Optional chezmoi data `llm_python` and
`llm_pwsh` select explicit executable paths for nonstandard installations.
Do not put credential values in those overrides or public declarations.

## Deliberate exceptions

- **OpenCode protected authentication is out of scope.** Its model projection
  still shares the catalog, with the same environment references and client
  schema as before. No wrapper or credential plugin is installed. Once the old
  environment key is removed, supply OpenCode authentication separately.
- **MCP credential delivery is out of scope.** Existing client MCP references to
  `CONTEXT7_API_KEY` and `GITHUB_PERSONAL_ACCESS_TOKEN` remain. This refactor stops
  exporting them; arrange external process-level delivery if those tools need
  them. A model-provider helper does not authenticate MCP servers.
- **Claude Code and Copilot CLI** keep native login ownership. Claude's Windows
  login file is ACL-protected, not an encrypted vault. Copilot documents Windows
  Credential Manager with a possible plaintext fallback. Neither login store is
  inspected, imported, or rewritten by this setup.
- **WSL/remote/cloud execution** is not covered by the Windows helper contract.
  Windows paths and CurrentUser-DPAPI data are not portable credentials.

## Human-only migration

Setup removes the old secret-bearing *profile source entries*, but does **not**
clear any existing persistent user-environment credentials. It also does not
alter saved client login entries. Finish the handoff yourself:

1. Ensure the encrypted source contains the selected providers' keys and the age
   identity is available. Preview privately: the initial diff can show plaintext
   values being removed from the previously deployed profile. Subsequent source
   rendering is secret-free.
2. Apply, then restart Codex/Desktop/Pi. For Desktop, use native Windows execution
   and a new task. Check the intended provider and route, not a model's self-report.
3. Pi saved `auth.json` entries take precedence over `models.json` helpers. Use
   Pi's supported logout flow for conflicting managed-provider entries if present;
   do not delete the whole auth file or unrelated native logins. Do not copy keys
   into a login form to test the helper.
4. Review the separate cleanup script, then run its preview:

   ```powershell
   pwsh -NoProfile -File ./docs/cleanup-llm-environment.ps1
   pwsh -NoProfile -File ./docs/cleanup-llm-environment.ps1 -Apply
   ```

   `-Apply` requires confirmation. Add `-IncludeMcp` only after deciding how to
   supply MCP credentials externally. The allowlist includes retired provider
   keys and Claude routing overrides; inspect it for keys you use elsewhere.
   The script prints names, never values, and is never invoked by chezmoi.
5. Restart affected clients and their launchers/terminals. A child process cannot
   update its parent's environment; existing processes keep inherited values.
   Remove plaintext editing copies/backups of old profiles as appropriate.

Deleting local copies is not revocation. Revoke a compromised or retired key at
its provider. Do not add environment cleanup back to the automatic apply path.

## Security limits and recovery

The goal is no intentional plaintext persistence of managed provider keys in
profiles, configuration, or the Windows user environment **after the manual
handoff**. Keys still enter memory while publishing and making requests, and
clients may cache them. DPAPI does not isolate a secret from arbitrary code
running as the same Windows user. No helper can make a bearer token never exist
in plaintext.

The encrypted source remains authoritative. The local DPAPI store is disposable
and user/machine-bound, not a portable backup. Restore the age identity securely
and reapply to recover on a new installation. Protect that identity and avoid
leaving ignored `secrets.yaml` editing copies: possession of a usable identity
plus ciphertext defeats protection of the derived store. `.gitignore` is not
encryption. Native auth and externally managed credentials remain exceptions.

## Validation

```powershell
python -B -m unittest discover -s tests
chezmoi diff
```

Tests use disposable homes, fixture keys/ciphertext, and isolated process state;
they do not inspect real credentials or contact inference services. The tests
cover the shared projections, template integration, credential publication and
retrieval, and no-export/no-auto-cleanup policy. Real Desktop/provider acceptance
is a separate human check after apply. Supporting research and primary-source
links are in [llm-credential-storage-research.md](llm-credential-storage-research.md).
