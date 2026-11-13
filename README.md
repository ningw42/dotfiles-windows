# Windows dotfiles

Personal Windows configuration managed with [chezmoi](https://www.chezmoi.io/).
The setup is PowerShell-first and includes application provisioning, terminal and
CLI configuration, themes, secrets, and coding-agent tooling.

For repository maintenance rules, see [`AGENTS.md`](AGENTS.md).

## Bootstrap

Install chezmoi, clone the source without applying it, and provision the required
applications:

```powershell
chezmoi init github.com/ningw42/dotfiles-windows
winget configure -f ~/.local/share/chezmoi/configuration.dsc.yaml
```

Place the age identity at `~/.config/chezmoi/key.txt`, then preview and deploy the
dotfiles. Existing installations that predate the shared-skill publisher or
provider-owned credentials must review the [legacy handoff](docs/legacy-migrations.md).
Existing plaintext credential exports also require the
[human-only protected-credential handoff](docs/llm-configuration.md#human-only-migration):

```powershell
chezmoi diff
chezmoi apply
```

The first initialization prompts for the colorscheme, password manager, and Git
identity. LLM routing is declared in `.chezmoidata/llm-harnesses.toml`, not a
machine-local provider prompt. The prompted answers are stored in the generated
`~/.config/chezmoi/chezmoi.toml`; `.chezmoi.toml.tmpl` defines the available
choices.

## What is managed

- **Shell and developer tools:** PowerShell, Git, SSH, Neovim, Yazi, fzf,
  starship, bat, delta, lazygit, gitui, eza, bottom, btop, and related tools.
- **Terminals:** Windows Terminal, WezTerm, Rio, Alacritty, Zellij, and HerdR.
- **Coding agents:** Claude Code, Codex, Copilot CLI, OpenCode 2, and pi, plus
  shared MCP/skills infrastructure, release-matched HerdR integrations, and a
  Claude/Copilot status line.
- **Bootstrap:** `configuration.dsc.yaml` installs Scoop packages, WinGet apps,
  PowerShell modules, and per-user fonts. WinGet resources request the latest
  available manifest version; WezTerm uses the nightly channel.

Five colorschemes are available: Catppuccin Latte, Frappé, Macchiato, and Mocha,
plus Gruvbox Dark. Templates and checksum-pinned chezmoi externals keep themes in
sync across applications.

## Shared agent skills

Chezmoi acquires immutable upstream snapshots, while `manage_skills.py` publishes
skills from `agent_skills.sources` in `.chezmoidata.toml`. Each source has a
home-relative `directory` and its own **optional**, declarative `include` and
`exclude` filters:

| Source filters | Published selection |
| :--- | :--- |
| Neither supplied | All upstream-declared skills |
| `exclude` only | All upstream-declared skills, minus exclusions |
| `include` supplied | That selection, minus any exclusions (exclusions win) |

An omitted `include` is different from `include = []`: an explicitly supplied
include must be a nonempty list. `exclude = []` is valid and equivalent to omitting
exclude. Nulls, malformed paths/declarations, missing inputs, and selections with
no remaining skills are errors **before mutation**, not requests to remove owned
outputs. Remove a source from the mapping to intentionally retire its outputs.
Filter paths remain literal, source-relative file/subtree paths using `/`, not
globs; existing configurations retain their meaning, including support-file
includes and exclusions. Including a literal `SKILL.md` also retains that skill's
support directory, subject to explicit exclusions.

Default-all follows a root plugin's `skills` declarations; without that field,
it uses immediate skill directories under `skills/` (or a root `SKILL.md`). A
source that is a marketplace enumerates its declared local plugin sources using
the same rules. Discovery does not recursively search examples, drafts, templates,
or unlisted categories. A root plugin takes precedence over a repository's
marketplace wrapper. Selected skill directories retain their support trees;
default discovery also retains licenses, conventional plugin support directories
(`scripts`, `references`, `assets`, `agents`, `output-styles`), and declared
agent/style/hook resources. Unrelated repository metadata and installers are not
implicitly imported. Selected links/reparse points are refused, not followed.

Matt Pocock intentionally has **no filters**: the pinned root plugin manifest
defines the selection; unlisted skills stay out. New upstream declarations become
available on a reviewed pin refresh without a separate allowlist edit. HumanLayer
intentionally retains `include = ["plugins/show-me/skills/show-me", "LICENSE"]`:
this filtered source remains show-me-only, not the whole marketplace. Review
intentionally filtered sources separately when widening their scope.

Each configured source keeps its existing generated plugin name and output path.
An unfiltered marketplace source bundles declared plugins under their original
relative paths, retains their normalized plugin metadata, and rebases agent,
style, and hook references into the generated root manifest. Its filtered
marketplace metadata is kept as inert `.claude-plugin/upstream-marketplace.json`
provenance. Skill lists are regenerated from retained skills; missing declared
support references fail validation rather than producing dangling manifest paths.
Remote marketplace entries, component overrides, and unsupported active plugin
fields are refused; publication never acquires dependencies or runs upstream code.

The publisher owns only outputs attested by
`~/.config/claude-code-chezmoi/.skill-publisher.json`:

- filtered plugins under `generated-skills/`;
- their absolute links under `~/.agents/skills/`; and
- the generated `.claude-plugin/marketplace.json`.

Raw snapshots, repo-authored skills, HerdR's generated skill, `plugins/user-mcps`,
and Claude's plugin registry/cache keep their existing owners. A lock serializes
writers, and foreign or modified outputs are refused rather than adopted. Plugin
versions are derived from selected bytes, executable bits, normalized metadata,
and filters, so support-file changes invalidate Claude's cache while a root
plugin's upstream version field or an unselected file does not. Publication never
activates plugins; after it succeeds, use native Claude commands to refresh the `chezmoi`
marketplace and install or update its plugins.

A leftover `.skill-publisher-work` means a transaction or cleanup was interrupted.
Preserve it and independent backups, inspect the receipt and current outputs, and
reconcile them manually before clearing the blocker. Do not delete a receipt to
force adoption. Caught pre-commit failures normally restore the previous state,
but process termination is not automatically recoverable and concurrent readers
do not receive an atomic multi-file snapshot.

### Deployment

`chezmoi apply` runs the publisher after acquiring the configured snapshots.
For pre-publisher installations, complete the
[human-only legacy handoff](docs/legacy-migrations.md#shared-skills-publisher)
first. Keep an existing receipt and validate its recorded outputs; stop competing
applies before switching checkouts.

To preview publication separately, explicitly select the checkout and acquire
externals without lifecycle scripts (replace `$source` with the checkout path):

```powershell
chezmoi --source $source --refresh-externals=always apply --include=externals
& "$HOME/scoop/apps/python/current/python.exe" -X utf8 "$source/manage_skills.py" --home $HOME --dry-run
chezmoi --source $source --refresh-externals=never diff
# Human approval boundary:
chezmoi --source $source --refresh-externals=never apply
```

A scripted apply that can touch pi settings uses `--force`. The externals-only
apply deliberately excludes lifecycle scripts; it is acquisition, not
authorization to publish or migrate.

After publication, refresh Claude through its native interface:

```powershell
claude plugin marketplace update chezmoi
claude plugin install mattpocock-skills@chezmoi --scope user
claude plugin install humanlayer@chezmoi --scope user
```

Use `claude plugin update` instead of `install` for plugins already installed.
Preserve unrelated plugins, and restart or reload agents after publication and
cache changes.

## Pi

`dot_pi/` mirrors the portable pi settings from `nixfiles`, including the model
catalog, extension preferences, subagent/task defaults, and workflow routes.
Windows keeps PowerShell enabled and uses the checksum-pinned `pi-distribution`
external rather than Nix store paths. MCP comes from Pi's built-in support
reading the repo-managed `~/.pi/agent/mcp.json`.

Pi and OpenCode use `https://magpie.ningw.net`: Responses for GPT, DeepSeek,
and GLM, Anthropic Messages for Claude Haiku/Sonnet/Opus 5.5, and Google's native
Generative AI API for Gemini. Claude uses adaptive thinking, with
medium/high/medium effort defaults respectively; this does not change Claude
Code's subscription auth. Pi's generated Explore/Plan agents and all workflow
tiers still use `magpie-responses`. GPT-5.6 Sol sends the bare `gpt-5.6-sol`
request ID; Magpie selects Copilot's fast tier internally. Pi, OpenCode, Codex,
and Copilot CLI default to GPT-6 Astra at `xhigh` effort. Shared model facts,
defaults, and endpoint bindings live in `.chezmoidata/llm-*.toml`.
`render_llm_config.py` validates them and supplies the Pi, OpenCode, and Codex
chezmoi templates. Codex remains on Copilotd, Copilot CLI
uses its native authentication, and Claude Code uses subscription authentication.
Pi shows background agents in the above-editor widget with the below-editor
FleetView list disabled, matching `nixfiles`. Its workflow tiers and Explore/Plan
model routes remain independent of the interactive default.

Codex (including native Windows Desktop) and Pi retrieve credentials from a
CurrentUser-DPAPI-protected store published during `chezmoi apply`. Selected
providers require `copilotd_api_key` and `magpie_api_key` in `secrets.yaml.age`.
Rendering/diffing does not decrypt secrets. OpenCode protected authentication is
out of scope: its environment references remain, but credentials are no longer
exported by the profile or setup. See [LLM configuration and credential
lifecycle](docs/llm-configuration.md) for declaration ownership, prerequisites,
rotation, and the required human-only environment/login handoff.

DeepSeek Flash uses the bare `deepseek-flash` ID through Magpie's Responses
endpoint, which supplies gateway routing and failover; neither Pi nor OpenCode
registers the old direct `deepseek-responses` provider or versioned Magpie alias.
The PowerShell profile's `pi` function masks `DEEPSEEK_API_KEY` while launching
Pi and restores the shell's original value afterward, including on failure. The
externally supplied key remains available to other clients. This boundary applies
to `pi` in a profile-loaded PowerShell session; invoking `pi.exe` directly or using
`pwsh -NoProfile` bypasses it.

The NixOS Magpie server and Linux/macOS Moshi daemon/hooks are not deployed by
this Windows configuration. Magpie remains a remote service; no local gateway
installation is needed.

## OpenCode

OpenCode 2.2+ uses native discovery for global and project `.agents/skills` and
OpenCode skill roots. The PowerShell profile and persistent user environment set
`OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` to exclude both Claude roots without
disabling the whole compatibility scanner. Existing processes need restarting
after deployment to inherit the persistent setting. Repo-authored human-only
skills retain their explicit commands and invocation permissions.

RTK 1.1+ owns the native `~/.config/opencode/plugins/rtk.ts` plugin. Scoop ships
only the executable, so the RTK apply hook generates the embedded plugin with
`rtk init -g --opencode --no-patch`, temporarily redirecting `CLAUDE_CONFIG_DIR`
to avoid recreating Claude awareness files or patching its managed settings.
Chezmoi removes the old `rtk.js` adapter; the native plugin respects
`RTK_DISABLED` and OpenCode's agent-scoped shell permissions.

## Claude/Copilot statusline

`dot_config/statusline/statusline.py` shares the nixfiles implementation: session
input/output totals, cache-hit percentage and non-cache-read details, and a
width-aware layout. Narrow terminals fall back to three ANSI-safely truncated
rows. Claude supports multiline output; Copilot's host rendering of multiple
rows remains unverified. Pi retains its separate package-owned statusline.

## Secrets

`secrets.yaml.age` is committed; plaintext `secrets.yaml` is gitignored and must
never be committed. Chezmoi decrypts the file with
`~/.config/chezmoi/key.txt` during apply.

```powershell
age -d -i ~/.config/chezmoi/key.txt -o secrets.yaml secrets.yaml.age
age -e -r RECIPIENT_FROM_CHEZMOI_CONFIG -o secrets.yaml.age secrets.yaml
```

Re-encrypt after editing. The apply-time credential hook publishes selected
provider keys to a Windows CurrentUser-DPAPI-protected store; the source remains
authoritative. Credential values are not embedded in generated profiles,
configuration files, or apply scripts. Publication requires all selected
Codex/Pi provider fields and has no environment fallback.

| Encrypted field | Protected clients |
| :--- | :--- |
| `copilotd_api_key` | Codex CLI, native Windows Codex Desktop |
| `magpie_api_key` | Pi |

No credentials—including MCP keys—are exported by the PowerShell profile or
persistent-environment setup anymore. Existing environment entries are **not
removed automatically**. Use the preview-first, human-only
[cleanup script](docs/cleanup-llm-environment.ps1) after following the
[credential handoff](docs/llm-configuration.md#human-only-migration).
OpenCode and MCP environment references remain externally supplied; native
Claude/Copilot login stores remain client-owned.

DPAPI protects storage, not secrets in a running client's memory or against
arbitrary code running as the same Windows user. Protect the age identity and
remove plaintext editing copies when finished. Initial migration diffs may
expose old keys being removed from deployed files; review them privately.

## Maintenance

```powershell
chezmoi diff                              # preview rendered changes
chezmoi apply                             # deploy them
python update_externals.py --dry-run      # check external pins and checksums
python -B -m unittest discover -s tests    # run the repository test suite
python -B tests/acceptance_rtk.py -v       # check installed upstream RTK after upgrades
python dot_config/statusline/statusline.py test
```

All direct external pins live under `external_resources.pins` in
`.chezmoidata.toml`. The nested manifests select pins and declare target paths
and file/archive options; they do not contain their own URLs or checksums.

`update_externals.py` refreshes this structured data only. Pins without an
`update` recipe are re-hashed at their configured URL; `github_release` recipes
resolve the latest tag and source archive or named asset. `github_branch` recipes
resolve the configured branch head to a full commit SHA, then hash its immutable
source archive. HumanLayer follows `main` this way; its resolved `commit`, URL,
and checksum advance together without changing the reviewed skill selection.
All candidates must succeed before one atomic write. Successful changes use
canonical TOML formatting (values are preserved, comments/formatting are not);
no-op and dry-run checks leave the original bytes untouched. `--dry-run` still
makes network requests.
Exit codes are `0` unchanged, `1` changed/would change, and `2` failed.

After updating pins, refresh chezmoi's external cache while previewing:

```powershell
chezmoi diff --refresh-externals=always
```

When an external URL stays unchanged, chezmoi can retain an older download after
its checksum is bumped. A plain diff can then report a SHA-256 mismatch even when
fresh upstream bytes match the pin. Refresh the cache rather than replacing the
reviewed checksum with the stale cached content's hash. This does not deploy files.

The repository suite covers external updates and rendered manifests, shared-skill
publication and rollback, agent/provider configuration, PowerShell launch and
environment behavior, HerdR/RTK ownership, and Lazygit diff routing. Upstream RTK
hook rewriting and native OpenCode plugin compatibility live in the opt-in
`tests/acceptance_rtk.py` suite, outside default discovery. Run it after RTK
upgrades or when investigating compatibility. Repository-owned RTK integration
checks remain in the default suite. The statusline has a separate in-file suite,
invoked above.

Use Python 3.11+. Full validation across these suites needs Windows, chezmoi,
PowerShell, Node.js, RTK, Claude CLI, and directory-symlink support. Missing tools
or platforms cause explicit skips; check the summary before treating a run as
full validation. Native Claude acceptance fails rather than skips if its CLI is
available but symlinks cannot be created. Tests use temporary homes and stubbed
services rather than deploying to the real home or calling upstream APIs. The manifest fixture records reviewed targets, extraction options, and pin
IDs across theme/platform cases; pin values come from current `.chezmoidata.toml`.
Review that fixture when intentionally changing deployment layout, not for
ordinary pin refreshes.
