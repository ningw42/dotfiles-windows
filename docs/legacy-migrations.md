# Legacy migrations

Use these human-run procedures only for installations that predate the current
shared-skill publisher or provider-owned credentials. Fresh installations do not
need them. Normal deployment and maintenance live in [README.md](../README.md).

## Shared-skills publisher

The publisher refuses foreign outputs; it does not adopt the former static
marketplace or shared-skill links. Close competing applies and inspect the
deployment home before the first publisher-backed apply.

1. Close agent sessions. Back up and remove only Matt
   shared-skill links whose targets are skills declared by the old Matt plugin
   manifest. Remove `.agents/skills/show-me` only when it is a directory symlink
   whose target is exactly `.local/share/llm-agents/skills/show-me` under that
   deployment home. A regular directory, relative link, or unexpected target
   requires inspection. Delete links themselves, never their target trees.
2. Preserve the Matt archive, every local skill, HerdR links, and unrelated
   entries. Copy any custom fixed marketplace entries into
   `marketplace-base.json`, then back up and remove the old static live
   marketplace plus only the verified `plugins/mattpocock-skills` and
   `plugins/superpowers` directory links. Keep `plugins/user-mcps`, Claude
   registries, and caches.
3. Inspect and manually retire the unused Superpowers archive and old standalone
   `show-me` backing directory. The old `SKILL.md` must hash to
   `bea6da70a58096730b9aeb0bae293ddf4726103a98efc9ce13c481619942a810`.
   Preserve modified or extra files for review, and never remove the whole
   `.local/share/llm-agents/skills` parent.
4. Follow [shared-skill deployment](../README.md#deployment) to acquire snapshots,
   preview publication, and apply only after approval.
5. Retire `superpowers@chezmoi` through `claude plugin uninstall superpowers@chezmoi`.
   Inspect and remove any older remotely installed Superpowers plugin separately
   through Claude's CLI. Preserve unrelated plugins, registries, and caches.

If a publisher receipt already exists, validate its schema, recorded digests,
links, and marketplace first. A receipt identifies content rather than a checkout;
obtain an explicit ownership decision before using it from another checkout.
Never delete the receipt to force adoption.

## Provider-owned credentials

There are no credential compatibility aliases. The legacy fields `codex_api_key`,
`pi_api_key`, and `opencode_api_key` are ignored; `CODEX_API_KEY`, `PI_API_KEY`, and
`OPENCODE_API_KEY` are unconditionally cleared in both export paths, even if those
fields remain in the encrypted store. Pi and OpenCode use the provider-owned
`magpie_api_key`, not harness-specific secrets.

LiteLLM, Router Maestro, and Copilot Proxy are retired: their Codex
registrations and choices are removed, their secret fields are ignored, and
`LITELLM_API_KEY`, `ROUTER_MAESTRO_API_KEY`, and `COPILOT_PROXY_API_KEY` are cleared
in both export paths. Do not provision `litellm_api_key`, `router_maestro_api_key`,
or `copilot_proxy_api_key`; remove any leftover fields when editing the encrypted
store. The unused local Agent Maestro registration is also removed. Codex's
managed provider remains `copilotd`; saved retired selections stop rendering with
an instruction to use `chezmoi edit-config` to select it, never silently rerouting
requests. Running processes retain their inherited environments until restarted.

Before the first apply of the provider-key migration, move the copilotd
credential from `pi_api_key` to `copilotd_api_key` if needed, then remove the
legacy fields. Do not migrate retired LiteLLM credentials to copilotd or assume
that harness-named credentials are interchangeable. Check the intended service
before overwriting a provider key. Re-encrypt the store and privately review
`chezmoi diff` before applying; no key rotation is required.
