# Windows dotfiles

WinGet provisions the software; [chezmoi](https://www.chezmoi.io/) deploys my
PowerShell, terminal, editor, and coding-agent configuration to the Windows user profile.

## Setup

1. **Provision the tools.** Download and review [configuration.dsc.yaml](configuration.dsc.yaml).
   In a non-elevated PowerShell, run WinGet 1.9+ from the folder containing the file:

   ```powershell
   winget configure -f .\configuration.dsc.yaml
   ```

   The manifest installs chezmoi and uses Scoop's default `~/scoop` location.
   Accept WinGet's elevation prompt for the font-cache restart. New font installs
   need GitHub CLI authentication: if they fail at `gh api`, open a new terminal,
   run `gh auth login`, and rerun the configuration from the same folder.

2. **Initialize the dotfiles.** Open a fresh PowerShell 7 session so the new tools
   are on `PATH`. Clone the source without applying it:

   ```powershell
   chezmoi init ningw42/dotfiles-windows
   ```

   The [setup prompts](.chezmoi.toml.tmpl) ask for a colorscheme, password manager,
   Git name and email, and SSH **public** signing key.

3. **Prepare for the first apply.** Restore the age identity that decrypts this
   repo's `secrets.yaml.age` to `~/.config/chezmoi/key.txt`. Shared skills require
   directory symlinks; enable Windows Developer Mode if your user can't create them.

   If you're switching from Scoop's HerdR desktop defaults, quit the app and copy
   any layouts or mods you want to keep from `~/scoop/persist/herdr-app/data/` to
   `~/.config/herdr-app/`. Skip `herdr-app.sock`; chezmoi doesn't move the old data.

4. **Preview, then deploy.** Review the diff privately: existing files may contain
   old credentials. If the changes look right, apply them and restart your terminal
   and any running apps that need the new environment.

   ```powershell
   chezmoi diff
   chezmoi apply
   ```

## Coding agents

Install Claude Code or Codex separately if you use them. Claude Code and Copilot CLI
use their own sign-ins. Supply any required OpenCode or MCP environment variables yourself.

During `chezmoi apply`, the Codex and pi provider keys are decrypted and stored
using Windows DPAPI for the current user. After verifying that Codex and pi can
retrieve their keys, remove any obsolete credential exports; setup leaves them untouched.

For source-editing rules, external pin updates, and tests, see [AGENTS.md](AGENTS.md).
