---
name: subagent-policy
description: Match subagents to the main model and reasoning effort, with effectively unlimited turns.
disable-model-invocation: true
---

# Subagent Policy

On every subagent spawn or resume:

- **Parity:** Use the main conversation's model and reasoning effort. Pass both explicitly when supported; otherwise rely on inheritance.
- **Unlimited turns:** Omit turn-limit arguments such as `max_turns` when omission means unlimited; otherwise use the harness's documented unlimited setting. If a number is required with no unlimited value, use a large accepted ceiling (e.g. `1000000` or more) that will not realistically bind. Report unavoidable caps only when they could truncate the task.

Let already-running subagents continue when their turn ceiling is non-binding; a finite number alone does not warrant steering, stopping, or restarting.
