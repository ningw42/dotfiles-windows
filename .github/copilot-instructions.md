# GitHub Copilot instructions

**The full operating manual for this repo is [`AGENTS.md`](../AGENTS.md) at the
repo root. Read it and follow it** — it is the single source of truth shared by
every coding agent here (Claude Code, Copilot, Codex). The golden rules below are
only a safety net; `AGENTS.md` is authoritative and more complete.

- This is a **chezmoi**-managed **Windows / PowerShell** dotfiles repo. The repo
  root **is** the chezmoi source directory (`~/.local/share/chezmoi`); files here
  are sources/templates that `chezmoi apply` renders into `$HOME`.
- **Edit sources here, never the deployed targets.** `~/.gitconfig`,
  `~/Documents/PowerShell/...`, `~/.config/...` are generated and overwritten on
  every apply. Change the source, then re-apply.
- **Preview before deploying:** `chezmoi diff`, then `chezmoi apply`.
- **Forward slashes in templates** — use `/` and
  `{{ .chezmoi.homeDir | replace "\\" "/" }}`; raw Windows backslashes break
  JSON/template parsing.
- Any new repo-only doc/script at the root **must** be added to `.chezmoiignore`,
  or `chezmoi apply` will create it under `~/`.
- **Commits:** Conventional Commits with a scope (e.g. `feat(statusline): ...`);
  no `Co-authored-by` trailer.

See `AGENTS.md` for the chezmoi attribute table, template data variables, the
colorscheme/theming system, externals & checksums, age secrets, and the rtk
ownership boundary.
