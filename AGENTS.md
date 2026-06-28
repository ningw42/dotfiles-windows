# AGENTS.md

Agent guidance for this repository. Human-facing overview lives in [`README.md`](README.md);
this file is the operating manual for working **in** the repo.

## What this repo is

A [chezmoi](https://www.chezmoi.io/)-managed **dotfiles repo for Windows**. The repo root
**is** the chezmoi source directory (`~/.local/share/chezmoi`). Files here are sources/templates
that `chezmoi apply` renders into `$HOME`. The host is **Windows with PowerShell**; a Bash tool
is also available, but configs, paths, and scripts are Windows-first.

## Golden rules

1. **Edit sources here, never the deployed targets.** `~/.gitconfig`, `~/Documents/PowerShell/...`,
   `~/.config/...` etc. are generated and overwritten on every apply. Change the source in this repo,
   then re-apply.
2. **The repo root is the chezmoi source dir.** Every plain file at the root is treated as a source
   and would deploy to `~/` unless it's a `.chezmoi*` special file or listed in `.chezmoiignore`.
   Any new repo-only doc/script (like this file) **must** be added to `.chezmoiignore`.
3. **Preview before deploying:** `chezmoi diff`, then `chezmoi apply`.
4. **Forward slashes in templates.** Use `/` and `{{ .chezmoi.homeDir | replace "\\" "/" }}` for home
   paths; raw Windows backslashes break JSON/template parsing.
5. **Commits:** Conventional Commits with a scope (e.g. `feat(statusline): ...`, `chore(chezmoi): ...`).
   No `Co-authored-by` trailer (`includeCoAuthoredBy` is off).
6. **Purge orphaned targets when you stop managing a file.** Deleting or renaming a source — or
   switching a target to a different mechanism (inline tmpl → external, ccstatusline → custom script,
   one tool's config replaced by another) — does **not** remove the already-deployed copy. chezmoi
   simply stops tracking it and the stale file lingers in `$HOME`. Add the old target to
   `.chezmoiremove` (always templated) so `chezmoi apply` deletes it on every machine. Orphaned
   colorscheme theme files are the most common case; see [Colorscheme / theming](#colorscheme--theming-the-main-cross-cutting-concern).

## Core workflow

```bash
chezmoi diff                      # preview exactly what apply would change
chezmoi apply                     # render sources -> $HOME
chezmoi cat ~/.gitconfig          # show the rendered output of one target
chezmoi execute-template < f.tmpl # render a template snippet to check syntax
chezmoi doctor                    # environment / config health check
```

## chezmoi naming attributes used here

| Pattern | Meaning |
| :--- | :--- |
| `dot_foo` | deploys as `~/.foo` (hidden dotfile) |
| `readonly_foo` | deployed file is marked read-only (e.g. the PowerShell profile) |
| `*.tmpl` | Go-template; rendered with the data vars below |
| `.chezmoiscripts/run_onchange_*.ps1.tmpl` | script re-run when its (hashed) content changes |
| `.chezmoitemplates/<tool>/<scheme>` | shared partials pulled via `{{ template "tool/scheme" . }}` |
| `.chezmoiexternal.toml[.tmpl]` | remote files (themes/plugins) fetched + checksum-verified |
| `.chezmoiignore` | targets to skip (also where repo-only files are excluded) |
| `.chezmoiremove` | targets to delete on apply — **always processed as a template** |
| `*.age` + `encryption = "age"` | age-encrypted sources, decrypted at apply time |

## Template data variables

Defined in `.chezmoi.toml.tmpl` (prompted once, cached in the **generated**
`~/.config/chezmoi/chezmoi.toml`, which is *not* in this repo — don't edit it directly):

- `colorscheme` ∈ `catppuccin-latte` · `catppuccin-frappe` · `catppuccin-macchiato` · `catppuccin-mocha` · `gruvbox-dark`
- `password_manager` ∈ `1password` · `bitwarden`
- `git_username`, `git_useremail`, `git_signingkey`
- `codex_provider` ∈ `litellm` · `router-maestro` · `copilot-proxy`
- `claude_code_provider` ∈ `byokey` · `litellm` · `router-maestro` · `copilot-proxy`
- `claude_code_base_url` is derived from `claude_code_provider` in `.chezmoi.toml.tmpl`; update that
  derivation when adding or renaming Claude Code providers.

Secrets are pulled in templates via `include "secrets.yaml.age" | decrypt | fromYaml`.
Using a variable in a `.tmpl` that isn't declared in `.chezmoi.toml.tmpl` makes `apply` fail.

## Colorscheme / theming (the main cross-cutting concern)

Five valid schemes (above). `everforest-dark` exists as a few `.chezmoitemplates` assets but is **not**
a prompt choice. Themes are wired three different ways depending on the tool:

1. **Shared partials** — `{{ template "tool/scheme" . }}` / `includeTemplate` pulls from
   `.chezmoitemplates/<tool>/` (bottom, eza, gitui, starship, fzf, windows-terminal).
2. **Colorscheme-conditional externals** — a `.chezmoiexternal.toml.tmpl` downloads the matching
   upstream theme file (bat, alacritty, yazi flavors/plugins, rio, glow, lazygit, btop).
3. **Inline conditionals** — `{{ if eq .colorscheme ... }}` directly in a tmpl (wezterm, zellij, gitconfig delta features).

⚠️ **Sync gotcha:** colorscheme `if`-blocks are duplicated across `AppData/Local/nvim/init.lua.tmpl`,
`AppData/Roaming/yazi/config/init.lua.tmpl`, `AppData/Roaming/Zellij/config/config.kdl.tmpl`,
`dot_gitconfig.tmpl`, and the per-tool theme tmpls. Adding or
renaming a scheme means updating **all** of them *and* adding the matching `.chezmoitemplates/<tool>/<scheme>`
files / external entries — otherwise apply silently mis-themes a tool or fails on a missing template name.
Switching schemes can orphan the previous theme file; those are cleaned up in `.chezmoiremove`.

## Externals & checksums

Theme/plugin files come from `.chezmoiexternal.toml[.tmpl]` entries (`type`, `url`,
`checksum.sha256`, `refreshPeriod`). Most are templated for the active colorscheme; `dot_config/delta/`
is a plain `.toml`.

⚠️ **If you change an external's URL you must refresh its checksum**, or `chezmoi apply` fails the
integrity check. Run:

```bash
python update_externals.py            # rewrites stale sha256s in place
python update_externals.py --dry-run  # preview only
```

It rglobs every `.chezmoiexternal.toml*`, downloads each URL, and updates mismatched checksums
(exit `0` none / `1` updated / `2` errors).

## Secrets (age)

- `secrets.yaml.age` is committed (encrypted); plaintext `secrets.yaml` is **gitignored — never commit it**.
- Decrypted at apply time with the identity at `~/.config/chezmoi/key.txt` (not in repo). The recipient
  public key is in `.chezmoi.toml.tmpl`.

```bash
age -d -i ~/.config/chezmoi/key.txt -o secrets.yaml secrets.yaml.age          # decrypt to edit
age -e -r <recipient-from-.chezmoi.toml.tmpl> -o secrets.yaml.age secrets.yaml # re-encrypt after editing
```

Editing secrets means re-encrypting the `.age` blob. When that blob's content changes,
`.chezmoiscripts/run_onchange_windows-env.ps1.tmpl` re-sets the persistent user env vars
(`CODEX_API_KEY`, `CONTEXT7_API_KEY`, `GITHUB_PERSONAL_ACCESS_TOKEN`, …) for GUI apps.

## AI coding tooling + the rtk ownership boundary

Managed agent configs: `dot_claude/` (Claude Code), `dot_codex/`, `dot_copilot/`,
`dot_config/opencode/`. Provider URLs switch off the `claude_code_provider` / `codex_provider`
data vars. A local MCP **plugin marketplace** lives in `dot_config/claude-code-chezmoi/` and is
registered via `extraKnownMarketplaces` + `enabledPlugins` in `dot_claude/settings.json.tmpl`.

- **MCP server list is mirrored in several files** — `dot_codex/config.toml.tmpl`,
  `dot_copilot/mcp-config.json`, `dot_config/opencode/opencode.json`, and
  `dot_config/claude-code-chezmoi/plugins/user-mcps/dot_mcp.json`. Keep shared server details in
  sync; Copilot's config currently omits `github`.
- **Copilot repo instructions** live in `.github/copilot-instructions.md` as a short safety-net
  pointer back to this file. If the golden rules change, keep that file's summarized bullets aligned.
- **Claude Code skills** live in the `user-skills` plugin (already registered in `marketplace.json`
  and enabled as `user-skills@chezmoi`). Add a skill by creating
  `dot_config/claude-code-chezmoi/plugins/user-skills/skills/<name>/SKILL.md` — YAML frontmatter with
  `name` + `description`, then the skill body. Plain markdown (no `.tmpl` unless you actually need a
  data var). `chezmoi apply` deploys it; restart Claude Code to load the new skill.
- **Unified statusline:** `dot_config/statusline/statusline.py` serves both Claude Code and Copilot
  (dispatch arg `claude` | `copilot`). It has an in-file test suite:
  `python dot_config/statusline/statusline.py test`.

⚠️ **The `rtk` tool owns these generated files — do NOT add them to this repo or edit them as sources:**
`~/.claude/{CLAUDE,RTK}.md`, `~/.codex/{AGENTS,RTK}.md`, `~/.copilot/copilot-instructions.md`, and the
copilot rtk hook. They are (re)generated by `.chezmoiscripts/run_onchange_rtk-init.ps1.tmpl`, which runs
`rtk init -g` only when the rtk binary version changes (`--no-patch` keeps `settings.json` chezmoi-owned).
Note: that rtk-owned `~/.codex/AGENTS.md` (global) is **not** this repo's root `AGENTS.md` (project doc) —
don't confuse the two.

## Repo-local vs managed Claude config

- `.claude/` at the repo root = settings for an agent **working in this repo** (the permission
  allowlist, project MCP servers). `.claude/settings.local.json` is gitignored personal overrides.
- `dot_claude/` = the **managed** `~/.claude` that gets deployed to the home directory.

## Provisioning (bootstrap only)

`configuration.dsc.yaml` is a WinGet DSC config applied with `winget configure`. It is idempotent and
bootstraps Scoop (+ `extras` bucket), installs the Scoop/WinGet CLI tools and GUI apps, the PSFzf module,
and per-user fonts (Iosevkata / SarasaFixedSC, fetched via the authenticated `gh` API). The PowerShell
profile (`readonly_Documents/PowerShell/Microsoft.PowerShell_profile.ps1.tmpl`, templated) decrypts secrets,
sets env vars/aliases, initializes starship/zoxide/PSFzf, and short-circuits inside Codex sessions.

⚠️ **Per-user fonts need a FontCache restart, not `AddFontResource`.** The font resources install packs
to `%LOCALAPPDATA%\Microsoft\Windows\Fonts` + HKCU (no admin) and replace files **in place** on a version
bump. DirectWrite apps (Windows Terminal, WezTerm, VS Code, browsers) serve fonts from the **Windows
`FontCache` service**'s shared system collection — keyed by *path + last-write-time* — and ignore GDI's
`AddFontResource` / `WM_FONTCHANGE`. So an in-place replacement leaves a dangling reference (DirectWrite
returns `DWRITE_E_FILENOTFOUND`) and the new font stays unusable until that cache is rebuilt — which
otherwise needs a full reboot. Each font `SetScript` therefore runs a best-effort `Restart-Service
FontCache` when a pack actually updates (uses the elevation `winget configure` provides; on a non-elevated
run it warns and falls back to reboot-required). `AddFontResourceEx` + `WM_FONTCHANGE` was verified **not**
to refresh DirectWrite, so the cache restart — not that GDI sequence — is the fix. The robust alternative,
if the per-user path ever acts up, is an all-users install into `C:\Windows\Fonts` (+ HKLM, always admin).

## Files that must NOT deploy to `$HOME`

These repo-only files are excluded in `.chezmoiignore`: `README.md`, `configuration.dsc.yaml`,
`update_externals.py`, `secrets.yaml`, `secrets.yaml.age`, `AGENTS.md`, `CLAUDE.md`. **Add any new
root-level doc or helper script to `.chezmoiignore`**, or `chezmoi apply` will create it under `~/`.

## Command cheat-sheet

| Task | Command |
| :--- | :--- |
| Preview / deploy | `chezmoi diff` · `chezmoi apply` |
| Render one target / snippet | `chezmoi cat <target>` · `chezmoi execute-template < f.tmpl` |
| Health check | `chezmoi doctor` |
| List ignored targets | `chezmoi ignored` |
| Refresh external checksums | `python update_externals.py [--dry-run]` |
| Statusline self-test | `python dot_config/statusline/statusline.py test` |
| Edit secrets | `age -d ...` → edit → `age -e ...` (see above) |
