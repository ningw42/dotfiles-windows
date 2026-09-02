---
name: develop-and-submit-pr
description: Apply feature-branch development conventions and submit a GitHub pull request.
disable-model-invocation: true
---

# Develop and Submit PR

Treat the complete implementation plan selected by the user as one branch lifecycle. Create exactly one feature branch for the entire plan; plan items, tickets, checkpoints, and subtasks do not start nested branch lifecycles. Complete each checkpoint before advancing.

The coordinating agent exclusively owns branch and worktree creation, publication, and retention. When this procedure is inherited by a development subagent, treat the branch and worktree supplied by the coordinator as authoritative, skip sections 1, 3, and 4, and perform only the assigned work from section 2.

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
6. Record every GitHub issue that drives the work for use in the pull request body.

Checkpoint: every plan requirement is implemented on the single feature branch, relevant verification passes, every completed task has a detailed feature-branch commit, and the feature worktree is clean.

## 3. Prepare the pull request

1. Start this section only after every plan item and subtask is complete. Record the feature tip and confirm its worktree is clean.
2. Select the GitHub repository, push remote, and target base branch from the recorded integration point and its upstream configuration. When the starting point was detached or the repository, remote, or base is ambiguous, ask the user to choose.
3. Refresh the target branch's remote state. Review the complete feature-branch diff and commit history against the selected base, confirming that they contain only the intended implementation. Preserve the feature commit history when the base has advanced; when the branch conflicts with the current base or repository guidance requires an update, ask the user whether to rebase or merge, then re-run relevant verification after the update.
4. Re-run relevant verification against the exact feature tip to be pushed.
5. Derive the pull request title and body from the plan and detailed feature-branch commit history. Follow repository conventions and templates, and preserve the outcome, significant changes, rationale, and verification performed.
6. When GitHub issues drove the work, put a GitHub closing keyword in the pull request body for each issue, for example `Closes #123` or `Closes owner/repo#123`.

Checkpoint: the repository, remote, base, and head are unambiguous; the reviewed feature tip is clean and verified; and the pull request title and body account for the complete change and every driving GitHub issue.

## 4. Publish the feature branch and submit the pull request

1. Check the selected repository for an existing remote branch or pull request with the same head. Protect unrelated remote history, and ask the user whether to update or reuse a matching branch or pull request instead of creating a duplicate.
2. Treat explicit invocation of this skill as authorization to push the recorded feature branch and create its pull request. Push the verified feature tip to the selected remote with upstream tracking.
3. Create a ready-for-review pull request from the feature branch to the selected base, or update the pull request chosen in step 1, unless the user or plan requested a draft.
4. Read the submitted pull request back from GitHub. Confirm its repository, URL, base, head, title, body, draft state, and issue-closing semantics match the prepared submission.
5. Leave the feature worktree clean and checked out on the feature branch. Retain the local feature branch and its worktree for follow-up changes.
6. Report the pull request URL, base and head branches, pushed tip, verification performed, included issue closures, and retained feature worktree.

Checkpoint: GitHub has the verified feature tip and one matching pull request, and the clean local worktree remains on the retained feature branch.
