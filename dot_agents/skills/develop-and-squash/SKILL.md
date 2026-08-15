---
name: develop-and-squash
description: Apply feature-branch development conventions and deliver one squash commit.
disable-model-invocation: true
---

# Develop and Squash

Treat the complete implementation plan selected by the user as one branch lifecycle. Create exactly one feature branch for the entire plan; plan items, tickets, checkpoints, and subtasks do not start nested branch lifecycles. Complete each checkpoint before advancing.

The coordinating agent exclusively owns branch and worktree creation, integration, and cleanup. When this procedure is inherited by a development subagent, treat the branch and worktree supplied by the coordinator as authoritative, skip sections 1, 3, and 4, and perform only the assigned work from section 2.

## 1. Pin the integration point

1. Have the coordinating agent read the repository guidance and the complete plan.
2. Record the starting worktree, branch or detached HEAD, and commit as the integration point.
3. Require a clean starting worktree. Preserve existing changes and ask the user how to handle them when it is dirty.
4. Create exactly one feature branch rooted at the recorded commit. Create it once before starting any implementation task, optionally in one separate worktree for the whole implementation.
5. Record the feature branch name and worktree path. Give both, together with the integration commit, to every development subagent.

Checkpoint: the integration point is recorded, its worktree is preserved, and the single feature branch for the complete plan exists at that exact commit.

## 2. Execute on the feature branch

1. Implement and verify every plan item on the recorded feature branch. Reuse it until the complete plan is finished.
2. Give every development subagent the parent session's model and reasoning effort. Pass both explicitly when the interface exposes them; otherwise use the runtime's inherited values. Treat any subagent allowed to modify or test the implementation as a development subagent.
3. Tell every development subagent that the branch lifecycle is already established. Require it to use the recorded feature branch and worktree without creating, switching, rebasing, squashing, or deleting branches or worktrees.
4. Run write-capable development tasks sequentially in that worktree. Parallelize only work that cannot change tracked files or Git state. Do not create task branches for concurrency without explicit user approval.
5. Require the agent responsible for each completed development task—including the main agent and every development subagent—to commit its task-owned changes on the same feature branch before handing off. Use one coherent task commit with a concise subject and a body that records the rationale, significant implementation decisions, and verification performed.
6. Record every GitHub issue that drives the work for use in the final commit message.

Checkpoint: every plan requirement is implemented on the single feature branch, relevant verification passes, every completed task has a detailed feature-branch commit, and the feature worktree is clean.

## 3. Squash onto the integration point

1. Start this section only after every plan item and subtask is complete. Record the feature tip, then confirm the destination is clean and still at the recorded integration commit. If it moved, ask the user whether to rebase or choose a new integration point.
2. Return to the original branch, or the original detached HEAD, and squash the feature branch into its worktree.
3. Re-run relevant verification against the squashed result.
4. Create exactly one commit, following the repository's commit-message conventions. Derive its subject and body from the plan and the detailed feature-branch commit history, preserving the outcome, significant changes, rationale, and verification.
5. When GitHub issues drove the work, put a GitHub closing keyword in the commit body for each issue, for example `Closes #123` or `Closes owner/repo#123`.
6. Leave the commit local. Treat pushing as a separate action requiring an explicit user request.

Checkpoint: the integration point has exactly one new commit, its resulting tree matches the verified feature result, its message captures the feature-branch history, and every driving GitHub issue has closure semantics.

## 4. Retire the feature branch

1. Remove the optional feature worktree after confirming it is clean and the squash commit is verified.
2. Delete the feature branch.
3. Report the squash commit, verification performed, deleted branch and worktree, included issue closures, and that no push occurred.

Checkpoint: the destination is clean at the squash commit, and the temporary feature branch and worktree no longer exist.
