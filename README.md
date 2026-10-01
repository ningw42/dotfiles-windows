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
  PowerShell modules, and per-user fonts.

Five colorschemes are available: Catppuccin Latte, Frappé, Macchiato, and Mocha,
plus Gruvbox Dark. Templates and checksum-pinned chezmoi externals keep themes in
sync across applications.

## Shared agent skills

Chezmoi acquires immutable upstream snapshots, while `manage_skills.py` publishes
reviewed subsets from `agent_skills.sources` in `.chezmoidata.toml`. Each source
has a home-relative `directory`, a nonempty list of literal file or subtree
`include` paths, and an optional `exclude` list. Paths are relative and use `/`;
they are not globs. The explicit list is the review boundary: refreshing an
upstream pin never adopts a newly promoted skill. Review and edit the includes
separately when changing the published set.

The publisher owns only outputs attested by
`~/.config/claude-code-chezmoi/.skill-publisher.json`:

- filtered plugins under `generated-skills/`;
- their absolute links under `~/.agents/skills/`; and
- the generated `.claude-plugin/marketplace.json`.

Raw snapshots, repo-authored skills, HerdR's generated skill, `plugins/user-mcps`,
and Claude's plugin registry/cache keep their existing owners. A lock serializes
writers, and foreign or modified outputs are refused rather than adopted. Plugin
versions are derived from selected bytes, executable bits, normalized metadata,
and filters, so support-file changes invalidate Claude's cache while an upstream
version field or unselected file does not. Publication never activates plugins;
after it succeeds, use native Claude commands to refresh the `chezmoi`
marketplace and install or update its plugins.

A leftover `.skill-publisher-work` means a transaction or cleanup was interrupted.
Preserve it and independent backups, inspect the receipt and current outputs, and
reconcile them manually before clearing the blocker. Do not delete a receipt to
force adoption. Caught pre-commit failures normally restore the previous state,
but process termination is not automatically recoverable and concurrent readers
do not receive an atomic multi-file snapshot.

### Human-run deployment and legacy handoff

Choose the procedure only after inspecting the deployment home:

1. **Clean installation:** there are no old links, plugin archive links, or static
   marketplace to remove. If a publisher receipt already exists, first validate
   its schema, recorded digests, links, and marketplace. A receipt identifies
   content rather than this repository; obtain an explicit ownership decision
   before using it from another checkout, and stop competing applies.
2. **Legacy installation:** close agent sessions. Back up and remove only Matt
   shared-skill links whose targets are skills declared by the old Matt plugin
   manifest. Remove `.agents/skills/show-me` only when it is a directory symlink
   whose target is exactly `.local/share/llm-agents/skills/show-me` under that
   deployment home. A regular directory, relative link, or unexpected target
   requires inspection. Delete links themselves, never their target trees.
3. Preserve the Matt archive, every local skill, HerdR links, and unrelated
   entries. Copy any custom fixed marketplace entries into
   `marketplace-base.json`, then back up and remove the old static live
   marketplace plus only the verified `plugins/mattpocock-skills` and
   `plugins/superpowers` directory links. Keep `plugins/user-mcps`, Claude
   registries, and caches.
4. Inspect and manually retire the unused Superpowers archive and old standalone
   `show-me` backing directory. The old `SKILL.md` must hash to
   `bea6da70a58096730b9aeb0bae293ddf4726103a98efc9ce13c481619942a810`.
   Preserve modified or extra files for review, and never remove the whole
   `.local/share/llm-agents/skills` parent.
5. Explicitly select this checkout. Acquire externals without lifecycle scripts,
   preview the publisher, and inspect the complete diff before an authorized
   apply (replace `$source` with the checkout path):

   ```powershell
   chezmoi --source $source --refresh-externals=always apply --include=externals
   & "$HOME/scoop/apps/python/current/python.exe" -X utf8 "$source/manage_skills.py" --home $HOME --dry-run
   chezmoi --source $source --refresh-externals=never diff
   # Human approval boundary:
   chezmoi --source $source --refresh-externals=never apply
   ```

   A scripted apply that can touch Pi settings uses `--force`. The externals-only
   apply above deliberately excludes lifecycle scripts; it is acquisition, not
   authorization to publish or migrate.
6. Refresh Claude through its native interface, preserving unrelated plugins:

   ```powershell
   claude plugin marketplace update chezmoi
   claude plugin uninstall superpowers@chezmoi
   claude plugin update mattpocock-skills@chezmoi --scope user
   claude plugin install humanlayer@chezmoi --scope user
   ```

   Inspect and remove any older remotely installed Superpowers plugin separately
   through Claude's CLI. Restart or reload agents after publication and cache
   changes.

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

The tests cover the updater with mocked HTTP and compare real chezmoi-rendered
manifests against a pre-refactor deployment baseline. Rendering tests use isolated
temporary config/state and skip explicitly if chezmoi is unavailable.
