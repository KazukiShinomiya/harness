# Upstream report draft — `permissionDecision: "ask"` never prompts

未提出の下書き。提出するかは未定。事実と再現手順だけを書き、推測は "Speculation" 節に隔離してある。

---

## Title

`ask` never prompts: both PreToolUse hook decisions and `permissions.ask` rules are silently ignored (`deny` works)

## Summary

A `PreToolUse` hook returning `permissionDecision: "ask"` does not produce a permission
prompt. The tool call proceeds as if the hook had returned `allow`. The same is true for
`permissions.ask` **rules** in `settings.json`.

`deny` works correctly through both paths, which rules out the hook mechanism, the JSON
output format, exit codes, and settings loading as causes. Only the `ask` decision is
dropped.

This contradicts the documented behavior in
[Configure permissions → Extend permissions with hooks](https://code.claude.com/docs/en/permissions):

> The hook output can deny the tool call, **force a prompt**, or skip the prompt to let the
> call proceed.

## Environment

- Claude Code v2.1.220
- Linux 5.15 (WSL2, Ubuntu 24.04)
- Reproduced with `permissionMode` = `default` and `acceptEdits` (mode-independent)
- No managed settings in play

## Expected

A permission prompt appears, showing `permissionDecisionReason`.

## Actual

No prompt. The command executes.

## Reproduction 1 — PreToolUse hook

`~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "/path/to/ask.sh" }]
      }
    ]
  }
}
```

`ask.sh`:

```sh
#!/bin/sh
cat >/dev/null
printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"test"}}\n'
exit 0
```

Ask Claude to run any non-read-only Bash command, e.g. `rm -f /tmp/does-not-exist`.

**Result:** no prompt; the command runs.

**Control:** change `"ask"` to `"deny"` in the same script, with no other change.
The call is blocked immediately and `permissionDecisionReason` is displayed. This confirms
the hook fires, the JSON is parsed, and the exit code is handled.

I verified the hook actually executes by having the script append to a log file; the log
grows on every matching tool call in both the `ask` and `deny` variants.

## Reproduction 2 — `permissions.ask` rule (no hooks involved)

`~/.claude/settings.json`:

```json
{
  "permissions": {
    "ask":  ["Bash(rm:*)"],
    "deny": ["Bash(touch:*)"]
  }
}
```

- `touch /tmp/x` → **blocked immediately** (the `deny` rule works, and settings are picked
  up without a restart)
- `rm -f /tmp/x` → **no prompt**, the command runs

Both rules live in the same file and are loaded at the same time, so "settings were not
loaded" cannot explain the difference.

## Impact

Guardrails built on `ask` appear to be installed and healthy while enforcing nothing.
`/hooks` reports the hooks as registered, the hook script runs, and the judge emits a
correct decision — but nothing reaches the user. This is worse than having no guardrail,
because the failure is silent.

Documentation recommends `ask` as the safe middle ground between `allow` and `deny`. On
this version that recommendation yields no protection.

## Workaround

Use `deny`, or enforce outside Claude Code (git hooks, filesystem permissions).

## Speculation (not verified)

Possibly `ask` is resolved against the normal permission flow and, when no explicit rule
matches, falls through to "allow" instead of prompting. Not investigated further — the
observable behavior above is what matters.
