---
name: unlimited-subagent-turns
description: Allow subagents effectively unlimited turns.
disable-model-invocation: true
---

# Unlimited Subagent Turns

Spawn and resume every subagent with **effectively unlimited** turns. Omit turn-limit arguments such as `max_turns` when omission means unlimited; otherwise use the harness's documented unlimited setting. If the schema requires a number and has no unlimited value, use a large accepted ceiling (e.g. `1000000` or more) that will not realistically bind. Report unavoidable caps only when they could realistically truncate the task.

An already-running subagent with a non-binding ceiling satisfies this policy. Let it continue; a finite number alone is not a reason to steer, stop, or restart it.
