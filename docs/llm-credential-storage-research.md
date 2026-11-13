# Coding-client credential retrieval support

This note records the pre-implementation support investigation. The implemented
ownership, apply lifecycle, exceptions, and migration steps are documented in
[LLM configuration](llm-configuration.md); use that document for operation.

## Scope and conclusion

Research only: installed manifests identify **Codex 0.169.0, Pi 1.5.2 (earendil-works fork), OpenCode 2.3.0, Claude Code 2.1.323, Copilot CLI 1.0.110**. No credential files, secret values, or identities were inspected; no login, implementation, deployment, or end-to-end authentication test occurred. A separate in-memory DPAPI roundtrip with a non-secret fixture succeeded; it wrote no files.

The proposed **age source → apply hook → CurrentUser-protected store → one helper** has a plausible integration path through the interfaces below, not an end-to-end acceptance result. Client adapters still differ, but the protected-store implementation need not. Codex and Pi can invoke a helper directly. OpenCode needs a scoped launcher or a V2-specific runtime plugin to avoid using its persistent login store.

## Custom-provider clients

### Codex: native command retrieval; separate login storage

`[model_providers.copilotd.auth]` supports `command`, `args`, optional `cwd`, `timeout_ms` (default 5000), and `refresh_interval_ms` (default 300000; zero disables proactive refresh). The helper prints the bearer token to stdout. This can replace the existing PowerShell command's environment-variable lookup without placing the key in configuration. Do not combine this mechanism with `env_key`, `experimental_bearer_token`, or `requires_openai_auth`. [1]

`cli_auth_credentials_store = "keyring"` protects **Codex's cached login credentials**; it is not a declaration mapping each custom provider to a Windows credential entry. `auto` permits plaintext-file fallback; `keyring` fails when unavailable. The source distinguishes provider-scoped command authentication from the base login manager. Enabling login keyring storage does not protect `COPILOTD_API_KEY` in persistent environment/profile configuration: the helper must retrieve that independently. [1–2]

### Pi: verified `!command`, including this fork

Installed `docs/models.md`, read in full, explicitly permits `models.json` provider `apiKey: "!command"`; `$NAME` and `${NAME}` remain environment interpolation. Illustrative adapter: `"apiKey": "!pwsh -NoProfile -File C:/path/credential-helper.ps1 magpie"`. The helper must emit only the key. Documentation says model commands run at request time without caching. Tagged fork source confirms leading-`!` execution, trimmed stdout, and a 10-second execution timeout; it also contains cached and uncached resolver variants, so do not generalize this timing to every credential interface. [3]

Default `/login` storage is JSON-backed, not native Windows protected storage. Stored authentication outranks `models.json`; an existing stored credential could therefore bypass the proposed helper. No native Credential Manager selector was established. [3]

### OpenCode 2: do not confuse command login with runtime retrieval

Configuration substitution supports **`{env:NAME}` and `{file:path}`**, not Pi-style `!command` or a generic command substitution. File substitution reads plaintext; pointing it at encrypted bytes does not decrypt them. Current V2 configuration uses `providers`/`settings`/`package`; the existing `provider`/`options` pattern is V1-shaped and requires migration-aware handling. [4]

V2 does support integration authentication commands, but they execute during connection/login and **persist stdout as a key credential**. Credentials are stored as JSON-valued SQLite rows, not Windows vault entries on this reviewed path. This is not the desired nonpersistent helper interface; V1 documentation saying `auth.json` is not an accurate V2 storage description. [5]

Practical choices:

- **Scoped launcher:** call the helper, set `MAGPIE_API_KEY` only in the launched OpenCode server/process environment, then launch it. No persistent environment change; plaintext still exists in process memory and potentially descendants. An already-running server will not acquire the launcher's environment.
- **Custom V2 server plugin:** retrieve the key at runtime and supply authentication without saving it. V1 `auth.loader` examples are not drop-in: V2 replaces `auth` hooks with integration APIs and provider/request hooks. This is an implementation possibility, not tested support. [6]

## GUI and existing native logins

GUI support is client-specific: **Codex Desktop has an explicit Windows credential-helper contract**, documented below; other GUI clients remain unverified. A GUI launcher must reach the actual backend, not merely an already-running window. Do not promise general GUI parity or native vault support from CLI evidence.

Leave subscription logins unchanged: Claude Code documents Windows login storage in `.credentials.json` with inherited profile ACLs, unlike macOS Keychain. Copilot CLI documents Windows Credential Manager (`copilot-cli` service), with prompted plaintext fallback when unavailable. These are login-store behaviors, not reusable custom-provider helper contracts. [7–8]

### Codex Desktop on Windows: shared configuration, explicit helper support

**Documented, not inferred from CLI parity:** OpenAI's gateway guide explicitly tells Windows-app users to put provider settings in `%USERPROFILE%/.codex/config.toml`, restart the app, and use `[model_providers.<id>.auth]` with a Windows executable, `args`, timeout, and refresh interval. Its shared example configures `model`, `model_provider`, `base_url`, and `wire_api = "responses"`. Thus custom endpoints and command-backed bearer authentication are documented desktop capabilities, not CLI-only features. Use compatible model/catalog metadata; an arbitrary model alias alone is insufficient. [11]

- **Home/config:** The Windows guide explicitly says the app shares native Windows Codex's `%USERPROFILE%/.codex`. General configuration docs locate state under `CODEX_HOME` (default `~/.codex`). A shell-specific `CODEX_HOME`, CLI `--profile`, or `-c` invocation is not evidence that the desktop process uses the same override; compare effective configuration rather than assuming it. Provider/auth routing belongs in user-level configuration, not project-local overrides. [12–13, 1]
- **Environment/helper:** The gateway guide warns that a terminal variable may not reach a desktop-launched app and recommends resolved absolute helper paths. The current `copilotd` setup (`https://copilotd.ningw.net/openai/v1`, `pwsh` printing `$env:COPILOTD_API_KEY`) therefore has a documented configuration shape, but still depends on the app/backend finding PowerShell and receiving that variable. Parent inspection found the backend spawn environment derives from the app's `process.env`, not an already-open PowerShell session. **Inference:** use an explicit helper invocation independent of interactive PowerShell profiles; replacing the lookup with one Windows CurrentUser-DPAPI helper should avoid shell-secret inheritance for native local execution. This remains untested. Do not combine provider `auth` with `env_key`, `experimental_bearer_token`, or OpenAI-login authentication. [11, 13, 15]
- **Windows versus WSL:** The app supports Windows-native or WSL2 agents; changing agent environment requires restart, and integrated-terminal selection is independent. A separately launched WSL CLI defaults to Linux `~/.codex`, but this is **not** a blanket rule for the app's WSL modes: parent inspection found a legacy `spawnInsideWsl` path that exports Windows `CODEX_HOME` with `WSLENV` path conversion. Remote/other WSL paths remain unverified. Shared TOML does not make Windows helper paths or DPAPI portable; this conclusion is scoped to native local Windows. [12, 15]
- **Runtime/session boundary:** App-server is the documented rich-client backend. **Parent-agent local evidence:** this Store app resolves app-server to its bundled `app/resources/codex.exe`, whose `--version` reports `codex-cli 0.167.0-alpha.4.1`, not Scoop's `0.169.0`. Its bundle resolves home as `process.env.CODEX_HOME ?? path.join(os.homedir(), '.codex')`, reads `config.toml`, and consumes effective `model_provider`/`model_providers`; the GUI also requests backend `config/read` and `model/list`. This establishes shared configuration without shared binary/version. Restart after config changes and use a new task; current app-server docs describe provider-mismatch rejection for old threads and forking to change provider. [11, 14–15]
- **Cloud/remote:** Do not extend the local result to cloud orchestration or a remote host. OpenAI explicitly says custom providers and host-local paths do not carry over to Work Cloud through managed configuration. A Windows-user-bound helper needs the appropriate execution host and identity. [13]

**Version/testing limit:** Current official docs (some Codex URLs now redirect to ChatGPT Learn) and parent-reported bundle inspection are not an authentication acceptance test of `OpenAI.Codex 26.1106.6628.0`. Only the bundled executable's version was queried; no GUI launch, real user config/auth read, deployment, helper execution, or inference request occurred in this desktop investigation. Other desktop products require their own contracts.

## Windows storage and security limits

Windows DPAPI in `CurrentUser` scope protects local bytes using Windows-managed user credentials; normally the same user on the same computer can decrypt them (roaming-profile exceptions exist). No application-managed password needs to be stored beside the encrypted output. Use user scope, not `LocalMachine`, which permits other users on the computer to decrypt accessible ciphertext. PowerShell can call .NET `ProtectedData.Protect`/`Unprotect`; this is a Windows adapter, independent of the Python configuration renderer. [9]

Windows Credential Manager generic credentials offer another storage interface, but are readable by user processes. Neither generic credentials nor CurrentUser DPAPI enforce an agent-specific identity or require fresh approval on every retrieval. These are storage protections, not isolation from malicious code already running as the same user. A helper still returns a bearer token in plaintext through a captured pipe; clients may retain it in memory. A launcher fallback also exposes it to the target process environment and potentially descendants. [9–10]

Chezmoi would remain the lifecycle owner: apply derives the protected local store from age; helpers only retrieve; rotation and retirement are apply-time actions. The local store is disposable derived state, not a portable backup or second authority. Ordinary config rendering needs no secret values. Migration must remove old managed environment/profile copies and account for higher-priority saved client credentials; no existing credentials should be inspected or deleted without an explicit migration decision.

This does not establish an entirely encrypted-at-rest workstation: the repo's age identity path is `~/.config/chezmoi/key.txt`, and its README documents decrypting to an ignored plaintext `secrets.yaml` for editing. A copied usable age identity plus ciphertext can defeat protection of the derived store. Protect the identity and avoid leaving plaintext editing copies; do not assume `.gitignore` encrypts or deletes them. Existing native logins, particularly Claude's Windows file store, are separate exceptions.

## Sources

- Versions: `C:/Users/ningw/scoop/apps/{codex/0.169.0,pi-coding-agent/1.5.2,opencode2/2.3.0,claude-code/2.1.323,copilot-cli/1.0.110}/scoop-manifest.json:2`. Remote docs can advance beyond installed releases; tagged source was preferred for V2 behavior.
- [1] OpenAI [configuration reference](https://developers.openai.com/codex/config-reference) (`model_providers.<id>.auth.*`) and [authentication/storage](https://developers.openai.com/codex/auth#credential-storage).
- [2] Codex `rust-v0.169.0`: [provider auth manager, lines 313–339](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/model-provider/src/auth.rs#L313-L339); [login storage, lines 307–387](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/login/src/auth/storage.rs#L307-L387).
- [3] Installed `C:/Users/ningw/scoop/apps/pi-coding-agent/1.5.2/docs/models.md:19–23,65`; fork [resolver](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/resolve-config-value.ts#L138-L237) and [JSON-backed storage](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/auth-storage.ts#L326-L361).
- [4] OpenCode `v2.3.0`: [substitution, lines 25–80](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/core/src/config/variable.ts#L25-L80); [V2 custom providers](https://github.com/anomalyco/opencode/blob/v2.3.0/services/site/src/docs/content/providers.mdx#L59-L117). Context7 `/anomalyco/opencode` returned mixed V1/current references; these tagged sources resolve that ambiguity.
- [5] OpenCode `v2.3.0`: [command-result persistence, lines 496–505](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/core/src/integration.ts#L496-L505), [execution, lines 615–675](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/core/src/integration.ts#L615-L675), [credential SQL schema](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/core/src/credential/sql.ts), [credential writes, lines 191–216](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/core/src/credential.ts#L191-L216), [Windows database ACL handling, lines 85–88](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/core/src/database/database.ts#L85-L88).
- [6] OpenCode `v2.3.0` [plugin migration](https://github.com/anomalyco/opencode/blob/v2.3.0/services/site/src/docs/content/build/plugins/migrate-v1.mdx#L145-L223): V1 implementations do not run in V2; integration and request-hook migration targets.
- [7] Anthropic [authentication: credential management](https://code.claude.com/docs/en/authentication#credential-management).
- [8] GitHub [Copilot CLI: how credentials are stored](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/authenticate-copilot-cli#how-copilot-cli-stores-credentials).
- [9] Microsoft [CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) and [.NET ProtectedData](https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.protecteddata).
- [10] Microsoft [generic credentials](https://learn.microsoft.com/en-us/windows/win32/secauthn/kinds-of-credentials#generic-credentials) and [CredReadW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw).
- [11] OpenAI [Connect to a gateway](https://learn.chatgpt.com/docs/enterprise/connect-to-a-gateway), especially [Windows-app command-backed authentication](https://learn.chatgpt.com/docs/enterprise/connect-to-a-gateway#configure-the-windows-app), provider/model setup, environment delivery, and restart/new-task verification.
- [12] OpenAI [Windows app](https://developers.openai.com/codex/app/windows), especially “Share config, auth, and sessions with WSL” and agent-environment settings.
- [13] OpenAI [Advanced Configuration](https://developers.openai.com/codex/config-advanced), especially “Profiles,” “Config and state locations,” “Custom model providers,” and “Applying these examples to Local computer access with Work Cloud.”
- [14] OpenAI [App Server](https://developers.openai.com/codex/app-server), introduction and “Start or resume a thread.” Context7 `/openai/codex` additionally identified the primary [home-directory resolver](https://github.com/openai/codex/blob/main/codex-rs/utils/home-dir/src/lib.rs) and [app-server protocol README](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md); the desktop-specific conclusion rests on [11–12], not Context7's CLI-to-GUI extrapolation.
- [15] Parent-agent local metadata/bundle inspection, not repeated by the docs researcher: `C:/Program Files/WindowsApps/OpenAI.Codex_26.1106.6628.0_x64__2p2nqsd0c76g0/app/resources/` (`codex.exe --version`, `app.asar`; ASAR product version `26.1106.51428`). Reported bundle paths/functions resolve Codex home, read effective provider configuration and `runCodexInWsl`, and choose the bundled app-server executable; no authenticated runtime behavior was tested.
