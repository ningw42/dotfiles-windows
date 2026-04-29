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
| PowerShell Profile                                              | N            | `dot_config\readonly_Documents\PowerShell\Microsoft.PowerShell_profile.ps1` | `~\Documents\PowerShell\Microsoft.PowerShell_profile.ps1` |

### Component specific notes

#### neovim
Everything is a carbon copy of the configs in my nixfiles, except `AppData\Local\nvim\lua\plugins\windows.lua`, which holds the Windows specific stuffs. e.g. mason.nvim as the language server manager.

#### git
git config is a template to redact personal information from the public copy. When initializing the local repository with `chezmoi init --apply github.com/ningw42/dotfiles-windows`, it should prompt for the required parameters.

### Template

chezmoi's [template](https://www.chezmoi.io/user-guide/manage-machine-to-machine-differences/) enables machine specific config by realizing a template with machine specific parameters managed by chezmoi. You will be asked for those machine specific parameters upon `chezmoi init`. After that, they are stored in chezmoi's configuration (`~\.config\chezmoi\chezmoi.toml`). Interestingly, chezmoi's configuration is also generated from a special template `.chezmoi.toml.tmpl`.

### Secrets

Secrets are managed with [age](https://github.com/FiloSottile/age) encryption. The encrypted blob `secrets.yaml.age` is committed to the repo. On `chezmoi apply`, it is decrypted using the age private key at `~/.config/chezmoi/key.txt`.

> **Note:** [SOPS](https://github.com/getsops/sops) would be preferable here (it encrypts only values, keeping YAML keys readable for meaningful diffs), but chezmoi does not have native SOPS support ([feature request](https://github.com/twpayne/chezmoi/issues/3823)).

The plaintext `secrets.yaml` is gitignored and should never be committed.

```bash
# decrypt
age -d -i ~/.config/chezmoi/key.txt -o secrets.yaml secrets.yaml.age

# encrypt (after editing secrets.yaml)
age -e -r age1chwluerpyq4p9e340eeqatgm70939x769h7teh3tmr09f564hpyqdz2urt -o secrets.yaml.age secrets.yaml
```
