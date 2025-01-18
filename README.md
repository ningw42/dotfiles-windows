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

| Component                                                       | Is Template? | Source                                                                      | Destination                                               |
| :-------------------------------------------------------------- | :----------- | :-------------------------------------------------------------------------- | :-------------------------------------------------------- |
| git config                                                      | Y            | `dot_gitconfig.tmpl`                                                        | `~\.gitconfig`                                            |
| [neovim](https://github.com/neovim/neovim) configs              | N            | `AppData\Local\nvim`                                                        | `~\AppData\Local\nvim`                                    |
| [rio](https://github.com/raphamorim/rio) configs                | N            | `AppData\Local\rio`                                                         | `~\AppData\Local\rio`                                     |
| [alacritty](https://github.com/extrawurst/gitui) configs        | N            | `AppData\Local\alacritty`                                                   | `~\AppData\Roaming\alacritty`                             |
| [gitui](https://github.com/extrawurst/gitui) configs            | N            | `AppData\Local\gitui`                                                       | `~\AppData\Roaming\gitui`                                 |
| [neovide](https://github.com/neovide/neovide) configs           | N            | `AppData\Local\neovide`                                                     | `~\AppData\Roaming\neovide`                               |
| [yazi](https://github.com/sxyazi/yazi) configs                  | N            | `AppData\Local\yazi`                                                        | `~\AppData\Roaming\yazi`                                  |
| [fastfetch](https://github.com/fastfetch-cli/fastfetch) configs | N            | `dot_config\fastfetch`                                                      | `~\.config\fastfetch`                                     |
| [wezterm](https://github.com/wez/wezterm) configs               | N            | `dot_config\wezterm`                                                        | `~\.config\wezterm`                                       |
| [starship](https://github.com/starship/starship) configs        | N            | `dot_config\starship.toml`                                                  | `~\.config\starship.toml`                                 |
| [glazewm](https://github.com/glzr-io/glazewm) configs           | N            | `dot_glze\glazewm\config.yaml`                                              | `~\.glzr\glazewm\config.yaml`                             |
| PowerShell Profile                                              | N            | `dot_config\readonly_Documents\PowerShell\Microsoft.PowerShell_profile.ps1` | `~\Documents\PowerShell\Microsoft.PowerShell_profile.ps1` |

### Component specific notes

#### neovim
Everything is a carbon copy of the configs in my nixfiles, except `AppData\Local\nvim\lua\plugins\windows.lua`, which holds the Windows specific stuffs. e.g. mason.nvim as the language server manager.

#### git
git config is a template to redact personal information from the public copy. When initializing the local repository with `chezmoi init --apply github.com/ningw42/dotfiles-windows`, it should prompt for the required parameters.

### Template

chezmoi's [template](https://www.chezmoi.io/user-guide/manage-machine-to-machine-differences/) enables machine specific config by realizing a template with machine specific parameters managed by chezmoi. You will be asked for those machine specific parameters upon `chezmoi init`. After that, they are stored in chezmoi's configuration (`~\.config\chezmoi\chezmoi.toml`). Interestingly, chezmoi's configuration is also generated from a special template `.chezmoi.toml.tmpl`.
