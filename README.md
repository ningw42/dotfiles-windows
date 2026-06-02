# dotfiles for Windows

Managed with [chezmoi](https://www.chezmoi.io/).

## Quick start

```powershell
chezmoi init --apply github.com/ningw42/dotfiles-windows
```

You will be prompted for machine-specific parameters (colorscheme, password manager, git identity, etc.). These are stored in `~\.config\chezmoi\chezmoi.toml`, which is itself generated from `.chezmoi.toml.tmpl`.

## Secrets

Secrets are managed with [age](https://github.com/FiloSottile/age) encryption. The encrypted blob `secrets.yaml.age` is committed to the repo. On `chezmoi apply`, it is decrypted using the age private key at `~/.config/chezmoi/key.txt`.

> **Note:** [SOPS](https://github.com/getsops/sops) would be preferable here (it encrypts only values, keeping YAML keys readable for meaningful diffs), but chezmoi does not have native SOPS support ([feature request](https://github.com/twpayne/chezmoi/issues/3823)).

The plaintext `secrets.yaml` is gitignored and should never be committed.

```bash
# decrypt
age -d -i ~/.config/chezmoi/key.txt -o secrets.yaml secrets.yaml.age

# encrypt (after editing secrets.yaml)
age -e -r age1chwluerpyq4p9e340eeqatgm70939x769h7teh3tmr09f564hpyqdz2urt -o secrets.yaml.age secrets.yaml
```

## Components

| Component | Template? | Source | Destination |
| :--- | :---: | :--- | :--- |
| [PowerShell](https://github.com/PowerShell/PowerShell) profile | Y | `readonly_Documents/PowerShell/` | `~/Documents/PowerShell/` |
| [git](https://git-scm.com/) | Y | `dot_gitconfig.tmpl` | `~/.gitconfig` |
| [SSH](https://www.openssh.com/) | N | `dot_ssh/` | `~/.ssh/` |
| [neovim](https://github.com/neovim/neovim) | Y | `AppData/Local/nvim/` | `~/AppData/Local/nvim/` |
| [wezterm](https://github.com/wez/wezterm) | Y | `dot_config/wezterm/` | `~/.config/wezterm/` |
| [Windows Terminal](https://github.com/microsoft/terminal) | Y | `AppData/Local/Packages/Microsoft.WindowsTerminal_*/` | `~/AppData/Local/Packages/Microsoft.WindowsTerminal_*/` |
| [starship](https://github.com/starship/starship) | Y | `dot_config/starship.toml.tmpl` | `~/.config/starship.toml` |
| [bat](https://github.com/sharkdp/bat) | Y | `dot_config/bat/` | `~/.config/bat/` |
| [delta](https://github.com/dandavison/delta) | N | `dot_config/delta/` | `~/.config/delta/` |
| [lazygit](https://github.com/jesseduffield/lazygit) | N | `AppData/Local/lazygit/` | `~/AppData/Local/lazygit/` |
| [yazi](https://github.com/sxyazi/yazi) | Y | `AppData/Roaming/yazi/` | `~/AppData/Roaming/yazi/` |
| [rio](https://github.com/raphamorim/rio) | Y | `AppData/Local/rio/` | `~/AppData/Local/rio/` |
| [alacritty](https://github.com/alacritty/alacritty) | Y | `AppData/Roaming/alacritty/` | `~/AppData/Roaming/alacritty/` |
| [gitui](https://github.com/extrawurst/gitui) | Y | `AppData/Roaming/gitui/` | `~/AppData/Roaming/gitui/` |
| [neovide](https://github.com/neovide/neovide) | N | `AppData/Roaming/neovide/` | `~/AppData/Roaming/neovide/` |
| [eza](https://github.com/eza-community/eza) | Y | `AppData/Roaming/eza/` | `~/AppData/Roaming/eza/` |
| [glow](https://github.com/charmbracelet/glow) | Y | `AppData/Local/glow/` | `~/AppData/Local/glow/` |
| [fastfetch](https://github.com/fastfetch-cli/fastfetch) | N | `dot_config/fastfetch/` | `~/.config/fastfetch/` |
| [Zed](https://github.com/zed-industries/zed) | N | `AppData/Roaming/Zed/` | `~/AppData/Roaming/Zed/` |
| [Claude Code](https://github.com/anthropics/claude-code) | Y | `dot_claude/` | `~/.claude/` |
| Claude Code MCP plugin (local marketplace, registered via `extraKnownMarketplaces`) | N | `dot_config/claude-code-chezmoi/` | `~/.config/claude-code-chezmoi/` |
| [Codex](https://github.com/openai/codex) | Y | `dot_codex/` | `~/.codex/` |

Many components pull colorscheme themes via [chezmoi externals](https://www.chezmoi.io/user-guide/include-files-from-elsewhere/) (see `.chezmoiexternal.toml` files).

## chezmoi scripts

| Script | Trigger | Purpose |
| :--- | :--- | :--- |
| `.chezmoiscripts/run_onchange_windows-env.ps1.tmpl` | Secret value changes | Sets `CODEX_API_KEY`, `CONTEXT7_API_KEY`, `GITHUB_PERSONAL_ACCESS_TOKEN` as persistent user-level env vars for GUI apps |
| `.chezmoiscripts/run_onchange_rtk-init.ps1.tmpl` | rtk version changes | Regenerates `~/.claude/{CLAUDE,RTK}.md` and `~/.codex/{AGENTS,RTK}.md` via `rtk init` (rtk owns these files) |

## Claude Code MCP plugin

User-scope MCP servers for Claude Code are shipped as a chezmoi-managed
local plugin marketplace at `~/.config/claude-code-chezmoi/`. The directory
contains:

- `.claude-plugin/marketplace.json` — marketplace manifest declaring one
  plugin (`user-mcps`)
- `plugins/user-mcps/.claude-plugin/plugin.json` — plugin manifest
- `plugins/user-mcps/.mcp.json` — user-scope MCP server config
  (brave-search, context7, exa, github)

The marketplace is registered in `~/.claude/settings.json` via
`extraKnownMarketplaces` (source type `directory`) and the plugin is
turned on through `enabledPlugins["user-mcps@chezmoi"]`. Because
both the Claude Code CLI and the Claude Desktop app read the same
`settings.json`, the plugin auto-loads in both — no PowerShell wrapper or
`--plugin-dir` flag required. Server names show up under
`plugin:user-mcps:<name>` (matching the
`mcp__plugin_user-mcps_*` tokens in `permissions.allow`).
