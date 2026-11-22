---
name: close-code-review
description: Close a code review by iterating with the existing implementer until both agree on every finding.
disable-model-invocation: true
---

# Close Code Review

Run this in the reviewer's session after review comments exist. The reviewer owns findings and acceptance; the implementer owns revisions and implementation-side verification. Either may ask the human for context, priorities, risk acceptance, or a decision at any point.

## 1. Establish the ledger

1. Give every actionable comment a stable ID, source or review axis, code location, concern, and checkable acceptance criterion. If none exist, report the review closed and stop.
2. Use the multiplexer the human names; otherwise use the one that unambiguously owns the reviewer's current session. An installed CLI alone is not evidence of an active session. If the choice is unclear, ask the human before contacting anyone. Load the matching skill (`herdr`, `herdr-core`, or `rex`) and follow its session and permission rules for discovery, messaging, and reading replies.
3. Invocation authorizes communication with the **existing implementer** for this review. Verify the agent's identity and repository or worktree before sending the ledger. If you cannot identify the intended implementer, ask the human to identify it rather than starting a replacement.

Checkpoint: every actionable comment is recorded, and the channel and implementer are identified.

## Sender identity

Prefix each peer message, including a reply left for the other agent to read, with `[agent:reviewer]` or `[agent:implementer]`. If the channel does not supply the sender's reply address, include it in the header: `[agent:reviewer via:<multiplexer> from:<live-address>]`. Use the sender's address as reported by the selected multiplexer. Address the human directly without a header, and attribute relayed human answers to them.

## 2. Request a revision

1. Send the complete open ledger. In the first handoff, include the sender-identity rule above so the implementer follows it throughout the loop. Invite the implementer to revise and verify the code or refute any ID with concrete reasoning and code, test, standard, or spec evidence.
2. When working on a feature branch, require every file-changing revision turn to end with one coherent commit before handoff. The commit records the addressed IDs and verification performed.
3. Wait for and read the implementer's complete reply. A delivery receipt or idle terminal is not a reply. Require the reply to account for every open finding ID.
4. Surface any human question from the implementer, record the answer in the ledger, and let the implementer finish the turn before re-reviewing it.

Checkpoint: every open ID has inspectable evidence, and each applicable feature-branch revision has its own commit.

## 3. Re-review

1. Inspect the actual diff, commits, relevant files, and verification results; the implementer's response is a map to evidence, not proof.
2. Mark each entry **fixed** when verified, **withdrawn** when the reviewer accepts contrary evidence, **waived** when the human accepts leaving it unresolved, or **open** otherwise.
3. Add stable IDs for actionable regressions introduced or exposed by a revision, bounded to the reviewed change and its governing standards or spec.

Checkpoint: every entry has an evidence-backed disposition, and every open entry states the remaining gap.

## 4. Iterate and confirm

1. Send only open and new entries and repeat sections 2–3.
2. Ask the human when the agents repeat positions without new evidence. Record the decision as a required fix, withdrawal, or waiver, then continue.
3. When no entry is open, send the final ledger to the implementer for explicit confirmation. Reopen any mismatch.
4. Verify the final diff, revision commits, and checks, then report all dispositions, human decisions, verification, and repository state. Leave squashing, pushing, and pull-request actions to the surrounding workflow.

Checkpoint: reviewer and implementer accept the same human-informed ledger, no entry remains open, and the reported repository state matches the verified implementation.
