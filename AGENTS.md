# AGENTS.md

This repository is the chezmoi source for a Windows user profile. Edit sources
here, not deployed files in `$HOME`. Keep [README.md](README.md) focused on
first-run setup; link to manifests and templates rather than copying their contents.

## Migrations: commit only what a fresh host needs

Commit the resulting configuration and any repeatable setup a new host needs.
If a step only imports, converts, moves, or removes state from an older setup,
give the user a **temporary PowerShell script** in your response to review and
run. Keep the script and its one-off instructions out of the repo; do not run
it automatically or add it to provisioning or apply hooks.

Deleting a source does not remove its deployed copy. Use `.chezmoiremove` when
a path must *stay absent* under the current configuration (such as an inactive
theme). Removing an old filename once is a migration, not an ongoing rule.

## Editing rules

- Check `git status` and preserve unrelated work. Use scoped Conventional Commits
  without a `Co-authored-by` trailer.
- Add repo-only root files to `.chezmoiignore` so chezmoi won't deploy them.
  Use forward slashes in templated home paths: `{{ .chezmoi.homeDir | replace "\\" "/" }}`.
- Change the source that owns the behavior: `configuration.dsc.yaml` for software,
  `.chezmoi.toml.tmpl` for machine prompts, `.chezmoidata/llm-*.toml` for shared
  model configuration.
- When changing a colorscheme, check per-app palettes and external manifests as
  well as shared templates. Keep shared MCP definitions aligned across clients;
  Copilot intentionally omits GitHub.
- For generated skills, hooks, and agent files, change the generator in
  `.chezmoiscripts/`, `manage_skills.py`, or the package pin. Don't import
  generated output or runtime caches. Preserve publisher receipts and recovery
  files rather than deleting them to force an overwrite.
- Commit `secrets.yaml.age`, never plaintext. Decrypt only in the apply-time
  credential hook, not while rendering templates or previewing a diff. Test
  credential changes with fixture keys and isolated homes.

## Validation and deployment

- **Templates or config:** preview with `chezmoi diff`. Apply only when deployment
  is requested. For an authorized automated apply that touches pi settings, use
  `chezmoi apply --force` after reviewing the diff; pi's runtime edits can prompt.
- **External pins:** keep URLs and SHA-256 hashes together in `.chezmoidata.toml`.
  Preview with `python update_externals.py --dry-run` (exit `1` means changes,
  `2` means failure). Review upstream changes, run `python update_externals.py`,
  then `chezmoi diff --refresh-externals=always` to avoid stale cached downloads.
- **Tests:** run the matching suite for a focused change. For docs, shared skills,
  or changes spanning tools, run `python -B -m unittest discover -s tests`.
  Outside discovery: `python -B tests/acceptance_rtk.py -v` after RTK upgrades,
  and `python dot_config/statusline/statusline.py test` for status-line changes.
