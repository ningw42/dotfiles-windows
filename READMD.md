# dotfiles for Windows

## Usage

### Initialize from repo

```powershell
# clone repo and apply
chezmoi init --apply github.com/ningw42/dotfiles-windows

# cd into local repo
cd $(chezmoi source-path)

# install dependencies
.\Install-Dependencies.ps1
```

### Edit dotfiles

```powershell
# cd into local repo
cd $(chezmoi source-path) # or cdcz, an alias of the same command, see https://www.chezmoi.io/user-guide/frequently-asked-questions/design/#why-does-chezmoi-cd-spawn-a-shell-instead-of-just-changing-directory

# make changes
```

### Apply changes

```powershell
chezmoi apply --verbose
```

### Components

| Component                                                       | Source                                                                      | Destination                                               |
| :-------------------------------------------------------------- | :-------------------------------------------------------------------------- | :-------------------------------------------------------- |
| [neovim](https://github.com/neovim/neovim) configs              | `AppData\Local\nvim`                                                        | `~\AppData\Local\nvim`                                    |
| [rio](https://github.com/raphamorim/rio) configs                | `AppData\Local\rio`                                                         | `~\AppData\Local\rio`                                     |
| [alacritty](https://github.com/extrawurst/gitui) configs        | `AppData\Local\alacritty`                                                   | `~\AppData\Roaming\alacritty`                             |
| [gitui](https://github.com/extrawurst/gitui) configs            | `AppData\Local\gitui`                                                       | `~\AppData\Roaming\gitui`                                 |
| [neovide](https://github.com/neovide/neovide) configs           | `AppData\Local\neovide`                                                     | `~\AppData\Roaming\neovide`                               |
| [yazi](https://github.com/sxyazi/yazi) configs                  | `AppData\Local\yazi`                                                        | `~\AppData\Roaming\yazi`                                  |
| [fastfetch](https://github.com/fastfetch-cli/fastfetch) configs | `dot_config\fastfetch`                                                      | `~\.config\fastfetch`                                     |
| [wezterm](https://github.com/wez/wezterm) configs               | `dot_config\wezterm`                                                        | `~\.config\wezterm`                                       |
| [starship](https://github.com/starship/starship) configs        | `dot_config\starship.toml`                                                  | `~\.config\starship.toml`                                 |
| PowerShell Profile                                              | `dot_config\readonly_Documents\PowerShell\Microsoft.PowerShell_profile.ps1` | `~\Documents\PowerShell\Microsoft.PowerShell_profile.ps1` |

### Component specific notes

#### neovim
Everything is a carbon copy of the configs in my nixfiles, except `AppData\Local\nvim\lua\plugins\windows.lua`, which holds the Windows specific stuffs. e.g. mason.nvim as the language server manager.

