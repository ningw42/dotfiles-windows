# AGENTS.md

Operating rules for agents working in this repository. The human-facing overview
is [`README.md`](README.md).

## Repository model

This is a Windows/PowerShell dotfiles repo, and its root is the chezmoi source
directory (`~/.local/share/chezmoi`). Files here are sources that `chezmoi apply`
renders into `$HOME`; they are not the deployed files themselves.

## Non-negotiable rules

1. **Edit sources here, never deployed targets** such as `~/.gitconfig`,
   `~/Documents/PowerShell/...`, or `~/.config/...`.
2. **Keep repo-only root files out of `$HOME`.** Add any new root-level doc or
   helper to `.chezmoiignore`. The ignore file is the authoritative list.
3. **Preview before deploying.** Run `chezmoi diff`; run `chezmoi apply` only
   when deployment is part of the task.
4. **Use forward slashes in templates.** For home paths use
   `{{ .chezmoi.homeDir | replace "\\" "/" }}`. Raw backslashes can break
   JSON or template parsing.
5. **Remove abandoned targets.** Deleting or renaming a source does not delete
   its deployed copy. Add orphaned paths to `.chezmoiremove`, which is always
   templated.
6. **Use scoped Conventional Commits** such as `feat(statusline): ...`. Do not
   add a `Co-authored-by` trailer.
7. **Do not overwrite unrelated work.** Check `git status` and keep edits scoped
   to the request.

## Working with chezmoi

```powershell
chezmoi diff                       # preview all rendered changes
chezmoi apply                      # deploy interactively
chezmoi cat ~/.gitconfig                 # render one managed target
Get-Content -Raw f.tmpl | chezmoi execute-template
chezmoi doctor                           # check the environment
chezmoi ignored                    # inspect ignored targets
```

Automated or agent-driven applies that may touch pi must use
`chezmoi apply --force`; otherwise a prompt about pi's runtime edits to
`~/.pi/agent/settings.json` can appear as a silent hang.

### Source conventions

| Source pattern | Meaning |
| :--- | :--- |
| `dot_foo` | Deploy as `~/.foo` |
| `readonly_foo` | Deploy read-only |
| `*.tmpl` | Render as a Go template |
| `.chezmoitemplates/...` | Shared template partial |
| `.chezmoiexternal.toml[.tmpl]` | Checksum-pinned remote content |
| `.chezmoiscripts/run_onchange_*` | Run when rendered content changes |
| `.chezmoiscripts/run_after_*` | Run after each apply |
| `*.age` | Age-encrypted source |

`.chezmoi.toml.tmpl` is the source of truth for prompted data, provider choices,
and the derived Claude Code base URL. Do not duplicate those lists elsewhere.
`.chezmoidata.toml` holds pinned external-release metadata. Templates load
secrets with `include "secrets.yaml.age" | decrypt | fromYaml`; referencing an
undeclared data variable makes apply fail.

## Cross-cutting configuration

### Colorschemes

The valid choices live in `.chezmoi.toml.tmpl`. Themes are implemented through a
mix of shared partials under `.chezmoitemplates/`, colorscheme-conditional
externals, and inline template conditionals. To find every integration, search
rather than relying on a copied list:

```powershell
rg -l colorscheme -g '*.tmpl' -g '*.toml' -g '*.lua' -g '*.ps1'
```

When adding or renaming a scheme, update every integration, add the required
partials/externals, and clean obsolete deployed theme files through
`.chezmoiremove`.

Rio is a special case: its Catppuccin external intentionally tracks the
`ningw42/rio` `feat/update-color-schema` branch. It no longer uses a filter.
Read the header in `AppData/Local/rio/.chezmoiexternal.toml.tmpl` before changing
its URL or checksum.

### Externals

Changing an external URL requires a matching SHA-256 update. Use:

```powershell
python update_externals.py --dry-run
python update_externals.py
```

The updater checks every `.chezmoiexternal.toml*` and refreshes GitHub release
source-archive and release-asset pins in `.chezmoidata.toml`. Exit codes are `0`
for unchanged, `1` for updated (or changes found in dry-run), and `2` for errors.
Inspect upstream changes before accepting a new checksum.

### Secrets

- Commit `secrets.yaml.age`, never plaintext `secrets.yaml`.
- The age identity is `~/.config/chezmoi/key.txt`; the recipient is declared in
  `.chezmoi.toml.tmpl`.
- After editing, re-encrypt the file. Changes cause
  `.chezmoiscripts/run_onchange_windows-env.ps1.tmpl` to refresh persistent user
  environment variables.

```powershell
age -d -i ~/.config/chezmoi/key.txt -o secrets.yaml secrets.yaml.age
age -e -r RECIPIENT_FROM_CHEZMOI_CONFIG -o secrets.yaml.age secrets.yaml
```

## Coding-agent configuration

Managed sources include `dot_agents/`, `dot_claude/`, `dot_codex/`,
`dot_copilot/`, `dot_config/opencode/`, `dot_pi/`, and the shared status line in
`dot_config/statusline/`.

- Keep shared MCP server definitions aligned in `dot_codex/config.toml.tmpl`,
  `dot_copilot/mcp-config.json`, `dot_config/opencode/opencode.json`,
  `dot_config/claude-code-chezmoi/plugins/user-mcps/dot_mcp.json`, and
  `dot_config/mcp/readonly_mcp.json` for pi. Copilot intentionally omits GitHub.
- `dot_config/statusline/statusline.py` serves Claude Code and Copilot via the
  `claude` and `copilot` dispatch arguments.
- The Claude marketplace combines the local MCP plugin with symlinks to pinned
  Superpowers and Matt Pocock skill archives. Release pins are in
  `.chezmoidata.toml`; archives are materialized by
  `dot_local/share/llm-agents/plugins/.chezmoiexternal.toml.tmpl`.
- `.chezmoiscripts/run_after_shared-agent-skills.ps1.tmpl` publishes the
  supported external skills under `~/.agents/skills` and refuses non-owned
  collisions. Repo-owned human-invoked skills live directly under
  `dot_agents/skills/`; the publisher preserves those non-owned directories.
- HerdR owns its release-matched generated hooks, plugins, and skill.
  `.chezmoiscripts/run_onchange_herdr-integrations.ps1.tmpl` extracts them from
  the installed binary in an isolated profile and publishes collision-checked
  skill links for Claude Code, Codex, pi, and OpenCode. Do not add those
  generated outputs as chezmoi sources or edit their deployed copies.
- Keep `.github/copilot-instructions.md` aligned if the non-negotiable rules
  change.

### RTK ownership

RTK owns its generated files; do not add them as chezmoi sources or edit deployed
copies.

- Codex remains prompt-based: `run_onchange_rtk-init.ps1.tmpl` generates
  `~/.codex/{AGENTS,RTK}.md`.
- Claude Code uses the `rtk hook claude` hook in
  `dot_claude/settings.json.tmpl`; its old awareness files are removed through
  `.chezmoiremove`.
- Copilot uses its generated `~/.copilot/hooks/rtk-rewrite.json`; the script
  deletes the redundant generated instruction file.
- Do not add pi to the RTK script. `pi-distribution` owns pi's RTK extension.

### pi ownership

The repo manages pi's agent JSON files and workflow settings under `dot_pi/`.
Pi's packaged extensions, packaged skills, and packaged themes come from the
checksum-pinned `pi-distribution` release external under
`dot_pi/agent/packages/`; the human-invoked skills under `dot_agents/skills/`
are deliberate additions to that package-owned set. The HerdR state extension
and skill are a separate generated integration owned by
`run_onchange_herdr-integrations.ps1.tmpl`, not by `pi-distribution`. Do not add
separate pi theme externals.

The `pi-distribution` tag and architecture-specific asset checksums live in
`.chezmoidata.toml`; `dot_pi/agent/settings.json` declares only its stable local
package path. Refresh the pin with `update_externals.py`, and let
`dot_pi/agent/packages/.chezmoiexternal.toml.tmpl` materialize it. Node.js, RTK,
and starship are runtime dependencies installed by `configuration.dsc.yaml`.
The PowerShell profile and persistent Windows environment set
`PI_STATUSLINE_STARSHIP`, disable pi's own version check, and opt out of install
telemetry to reproduce the nixfiles wrapper.

The global pi-subagents and pi-tasks defaults live in
`dot_pi/agent/{subagents.json,tasks-config.json}`. The global `Explore` override
is generated after every apply by
`.chezmoiscripts/run_after_pi-subagents-explore.ps1.tmpl` from the installed,
pinned pi-subagents sources; it deliberately removes the upstream model pin so
Explore inherits the parent model. Do not edit or add
`~/.pi/agent/agents/Explore.md` as a chezmoi source.

Pi also rewrites `settings.json` at runtime (for package/theme/version state), so
interactive apply may ask whether to overwrite it. This is expected: overwrite
to reassert the repo or skip to retain the runtime copy temporarily. Do not try
to mirror pi's volatile output. For non-interactive apply, use `--force`.

Do not add pi to the shared Python status line; `pi-distribution` provides pi's
starship-backed status-line extension.

### Local versus deployed Claude settings

- Root `.claude/` configures an agent working in this repository.
- `dot_claude/` deploys the managed user configuration to `~/.claude/`.
- `.claude/settings.local.json` is an ignored personal override.

## Provisioning

`configuration.dsc.yaml` is the idempotent WinGet configuration for Scoop,
command-line and GUI tools, PowerShell modules, and per-user fonts. Keep its
resources Windows-first.

Font updates deliberately install in user context, write a
`.cache-refresh-needed` sentinel, and let the elevated
`RestartFontCacheForFonts` resource restart `FontCache`. Do not replace this with
`AddFontResource`/`WM_FONTCHANGE`; those do not refresh DirectWrite. Mixed
security contexts require WinGet 1.9 or newer, and a failed elevation should
leave the sentinel for retry.

## Validation

Run the checks relevant to the change; do not deploy merely to validate.

| Change | Check |
| :--- | :--- |
| Any template/config | `chezmoi diff` |
| External URLs or pins | `python update_externals.py --dry-run` |
| External updater | `python -m unittest discover -s tests` |
| Shared status line | `python dot_config/statusline/statusline.py test` |
| Chezmoi environment | `chezmoi doctor` |
