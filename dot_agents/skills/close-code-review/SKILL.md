---
name: close-code-review
description: Close a code review by using Herdr to iterate with the implementer until both agree on every finding.
disable-model-invocation: true
---

# Close Code Review

Run this in the reviewer's session after review comments exist. The reviewer owns findings and acceptance; the implementer owns revisions and implementation-side verification. Either may ask the human for context, priorities, risk acceptance, or a decision at any point. Consensus means a shared final ledger that incorporates those answers, not that the agents settle everything unaided.

Invocation authorizes Herdr for this loop. Invoke and follow the `herdr` skill before issuing Herdr commands.

## 1. Establish the ledger

1. Give every actionable comment a stable ID, source or review axis, code location, concern, and checkable acceptance criterion. If none exist, report the review closed and stop.
2. Use Herdr to identify the existing implementer. Select it only when agent identity and repository or worktree context are unambiguous; otherwise ask the human to choose.

Checkpoint: every actionable comment is recorded, and one implementer is identified.

## 2. Request a revision

1. Send the complete open ledger and state explicitly that its findings come from a reviewer agent, not a human directive. Invite the implementer to revise and verify the code or refute any ID with concrete reasoning and code, test, standard, or spec evidence.
2. When working on a feature branch, require every file-changing revision turn to end with one coherent commit before handoff. The commit records the addressed IDs and verification performed.
3. Require the response to account for every open ID, then wait for and read the complete response through Herdr.
4. Surface any human question from the implementer, record the answer in the ledger, and let the implementer finish the turn before re-reviewing it.

Checkpoint: every open ID has inspectable evidence, and each applicable feature-branch revision has its own commit.

## 3. Re-review

1. Inspect the actual diff, commits, relevant files, and verification results; the implementer's response is a map to evidence, not proof.
2. Mark each entry **fixed** when verified, **withdrawn** when the reviewer accepts contrary evidence, **waived** when the human accepts leaving it unresolved, or **open** otherwise.
3. Add stable IDs for actionable regressions introduced or exposed by a revision, bounded to the reviewed change and its governing standards or spec.

Checkpoint: every entry has an evidence-backed disposition, and every open entry states the remaining gap.

## 4. Iterate and confirm

1. Send only open and new entries and repeat sections 2–3.
2. Ask the human whenever either agent requests input or the agents repeat positions without new evidence. Record the decision as a required fix, withdrawal, or waiver, then continue.
3. When no entry is open, send the final ledger to the implementer for explicit confirmation. Reopen any mismatch.
4. Verify the final diff, revision commits, and checks, then report all dispositions, human decisions, verification, and repository state. Beyond the required feature-branch revision commits, leave squashing, pushing, and pull-request actions to the surrounding workflow.

Checkpoint: reviewer and implementer accept the same human-informed ledger, no entry remains open, and the reported repository state matches the verified implementation.
