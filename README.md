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
provider-owned credentials must complete the [legacy handoff](docs/legacy-migrations.md)
first:

```powershell
chezmoi diff
chezmoi apply
```

The first initialization prompts for the colorscheme, password manager, Git
identity, and Codex provider. The answers are stored in the generated
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
and GLM, and Google's native Generative AI API for Gemini. Pi's generated
Explore/Plan agents and all workflow tiers also use `magpie-responses`. GPT-5.6
Sol sends the bare `gpt-5.6-sol` request ID; Magpie selects Copilot's fast tier
internally. Current defaults and model catalogs live in
`dot_pi/agent/{settings,models}.json` and
`dot_config/opencode/opencode.json.tmpl`. Codex remains on Copilotd, Copilot CLI
uses its native authentication, and Claude Code uses subscription authentication.

Magpie authentication requires `MAGPIE_API_KEY`. Add `magpie_api_key` to
`secrets.yaml.age` using the procedure below to publish it through both the
PowerShell profile and persistent user environment. If that optional secret is
absent, the templates preserve any externally supplied key; they do not copy
credentials from nixfiles' SOPS store.
Without a key, the Magpie models are configured but unavailable for inference.

DeepSeek Flash uses the bare `deepseek-flash` ID through Magpie's Responses
endpoint, which supplies gateway routing and failover; neither Pi nor OpenCode
registers the old direct `deepseek-responses` provider or versioned Magpie alias.
The PowerShell profile's `pi` function masks `DEEPSEEK_API_KEY` while launching
Pi and restores the shell's original value afterward, including on failure. The
stored key remains available to other clients. This boundary applies to `pi` in
a profile-loaded PowerShell session; invoking `pi.exe` directly or using
`pwsh -NoProfile` bypasses it.

The NixOS Magpie server and Linux/macOS Moshi daemon/hooks are not deployed by
this Windows configuration. Magpie remains a remote service; no local gateway
installation is needed.

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

Re-encrypt after editing. A `run_onchange_` script publishes the required values
as persistent user environment variables for desktop applications.

### Provider API keys

Credentials are named by provider, not by coding harness. Both the PowerShell
profile and persistent user environment export these optional secret fields:

| Encrypted field | Environment variable | Existing clients |
| :--- | :--- | :--- |
| `copilotd_api_key` | `COPILOTD_API_KEY` | Codex |
| `magpie_api_key` | `MAGPIE_API_KEY` | Pi, OpenCode |

A present field overrides that provider's environment key. An absent field
preserves an externally supplied key; without either, the provider cannot
authenticate. Unused providers need no field. Removing a field does **not** clear
a previously published provider key: explicitly clear it in both the shell and
user environment if retiring it. No provider falls back to a generic credential.
DeepSeek differs: an absent `deepseek_api_key` clears `DEEPSEEK_API_KEY` in both
export paths; a present field exports it for other clients. The PowerShell `pi`
launcher masks it only for the child process, as described above.

Retired harness-specific credentials and provider keys are ignored and their
environment variables are cleared in both export paths. For the exact retired
names and safe credential handoff, see
[provider-key migration](docs/legacy-migrations.md#provider-owned-credentials).
Running processes retain their inherited environments until restarted.

## Maintenance

```powershell
chezmoi diff                              # preview rendered changes
chezmoi apply                             # deploy them
python update_externals.py --dry-run      # check external pins and checksums
python -B -m unittest discover -s tests    # run the repository test suite
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
environment behavior, HerdR/RTK ownership, and Lazygit diff routing. The statusline
has a separate in-file suite, invoked above.

Use Python 3.11+ for the repository suite. Full validation needs Windows, chezmoi,
PowerShell, Node.js, RTK, Claude CLI, and directory-symlink support. Missing tools
or platforms cause explicit skips; check the summary before treating a run as
full validation. Native Claude acceptance fails rather than skips if its CLI is
available but symlinks cannot be created. Tests use temporary homes and stubbed
services rather than deploying to the real home or calling upstream APIs. The manifest fixture records reviewed targets, extraction options, and pin
IDs across theme/platform cases; pin values come from current `.chezmoidata.toml`.
Review that fixture when intentionally changing deployment layout, not for
ordinary pin refreshes.
