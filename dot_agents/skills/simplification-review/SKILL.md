---
name: simplification-review
description: Review code, diffs, or designs for contract-preserving simplification.
disable-model-invocation: true
---

# Simplification Review

Find complexity that can be removed, not merely moved. Keep the review read-only unless the user separately asks for changes.

## Fix the contract and scope

Name the artifacts under review and the sources that define required behavior, constraints, invariants, and safety boundaries. When another review supplies the scope and source precedence, inherit them unchanged and add one separate **Simplification** axis rather than repeating its Standards or Spec work.

When the primary review delegates independent axes, give one simplification reviewer this complete skill and the same scope and sources. Otherwise perform the axis directly. Load `codebase-design` when module shape, depth, locality, or the deletion test matters.

## Inspect three lenses

- **Over-engineering** — abstractions, indirection, generality, state, configuration, or test machinery not demanded by the contract. Apply the deletion test: prefer complexity that disappears over complexity relocated behind another shallow layer.
- **Over-defensive programming** — duplicate validation, impossible-state handling, silent fallback, retries, cleanup, or guards at trusted internal seams that hide defects or restate an established invariant. Preserve required checks at external or untrusted boundaries, and preserve mandated security, cancellation, exactness, and resource limits.
- **Repeated implementation** — behavior, policy, parsing, formatting, or test setup with one clear owner but multiple implementations. Extract only when the shared owner is honest and simpler than the repetition; incidental similarity is not a finding.

## Report

For each finding, provide:

1. exact artifact and evidence;
2. the contract that must remain true;
3. the unnecessary complexity and why it is unnecessary;
4. the smaller replacement shape;
5. the tests, invariants, or observations that would prove behavior is preserved.

Separate safe, contract-preserving simplifications from policy or behavior changes that need the user's decision. Rank findings by complexity removed versus change risk. Zero findings is valid; do not manufacture one.

The review is complete when all three lenses have been applied to the full scope and every finding proves a smaller shape against the fixed contract.
