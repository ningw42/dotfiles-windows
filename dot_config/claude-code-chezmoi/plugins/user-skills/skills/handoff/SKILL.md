---
name: handoff
description: Compact the current conversation into a handoff document for another agent to pick up.
argument-hint: "[project|temp] [what the next session will focus on]"
disable-model-invocation: true
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work.

Choose where to save it from the invocation arguments (`$ARGUMENTS`):

- **Project root** — if the arguments indicate the project (e.g. they contain `project`, `root`, `repo`, or `here`), save it to the root of the current project/workspace as `HANDOFF.md`.
- **System temp** — if they indicate temp (e.g. `temp`, `tmp`, or `system`), save it to the OS temporary directory (`$env:TEMP` on Windows; `$TMPDIR` or `/tmp` on Unix).
- **Unspecified** — default to the project root, saving as `HANDOFF.md`.

Always report the full path you wrote to.

Include a "suggested skills" section in the document, which suggests skills that the agent should invoke.

Do not duplicate content already captured in other artifacts (PRDs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

Treat any argument text beyond the optional location keyword as a description of what the next session will focus on, and tailor the doc accordingly.
