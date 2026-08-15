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

Place the age identity at `~/.config/chezmoi/key.txt`, then render the dotfiles:

```powershell
chezmoi apply
```

The first initialization prompts for the colorscheme, password manager, Git
identity, and LLM providers. The answers are stored in the generated
`~/.config/chezmoi/chezmoi.toml`; `.chezmoi.toml.tmpl` defines the available
choices.

## What is managed

- **Shell and developer tools:** PowerShell, Git, SSH, Neovim, Yazi, fzf,
  starship, bat, delta, lazygit, gitui, eza, bottom, btop, and related tools.
- **Terminals:** Windows Terminal, WezTerm, Rio, Alacritty, and Zellij.
- **Coding agents:** Claude Code, Codex, Copilot CLI, OpenCode, and pi, plus
  shared MCP/skills infrastructure and a Claude/Copilot status line.
- **Bootstrap:** `configuration.dsc.yaml` installs Scoop packages, WinGet apps,
  PowerShell modules, and per-user fonts.

Five colorschemes are available: Catppuccin Latte, Frappé, Macchiato, and Mocha,
plus Gruvbox Dark. Templates and checksum-pinned chezmoi externals keep themes in
sync across applications.

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

## Maintenance

```powershell
chezmoi diff                              # preview rendered changes
chezmoi apply                             # deploy them
python update_externals.py --dry-run      # check external pins and checksums
python -m unittest discover -s tests      # test the updater
python dot_config/statusline/statusline.py test
```

`update_externals.py` refreshes both checksum-pinned external files and the
GitHub release pins in `.chezmoidata.toml`.
