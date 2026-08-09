# Upstream report — `permissionDecision: "ask"` never prompts

**決着（2026-08-02）。新規 issue としては出していない。**

提出前に上流を検索したところ、同じ内容が既に 15 件以上報告されていた。最も近いのは
[anthropics/claude-code#79356](https://github.com/anthropics/claude-code/issues/79356) で、
下書きとほぼ同一の主張（hook 経路と `permissions.ask` の両方が効かない、`deny` は効く）。
ただし報告環境が Windows 11 / PowerShell / v2.1.215 で、`platform:windows` ラベルが付いていた。

そこで 16 件目の重複を作らず、**この下書きの対照実験を #79356 へのコメントとして出した**。
新規性はプラットフォームの否定——Linux / Bash / v2.1.220 でも同じことが起きるので、
`platform:windows` という分類は狭すぎる、という点にある。

投稿: <https://github.com/anthropics/claude-code/issues/79356#issuecomment-5157316941>

## 続報（2026-08-10、v2.1.226 で再検証）

**症状は「常に落ちる」ではなく「セッションによって落ちる」だった。** 同じ 2 通りの
再現手順を v2.1.226（ネイティブ Linux 6.8、Ubuntu 24.04.4）で撃ち直した。

| 経路 | v2.1.220 / WSL2 | v2.1.226 / セッション A | v2.1.226 / セッション B |
|---|---|---|---|
| Reproduction 1（PreToolUse の `ask`） | 素通し | **素通し** | **確認が出る** |
| Reproduction 2（`permissions.ask`） | 素通し | 素通し | — |

**A と B は同一機・同一版・同一 cwd・同一 `permissionMode`（default）・同一設定。**
違いはセッションだけで、同じ `rm -f /tmp/guardrails-manual-check` の結果が割れた。

セッション A の素通しは、フックが動いていないせいではない。切り分け済み:

- `guard.sh` の先頭にタイムスタンプを追記させると、Bash 呼び出しごとにログが 2 行増える
  （`hooks.json` の PreToolUse 定義 2 件が `Bash` にマッチするため）。**フックは発火している**
- 判定器の既定を `deny` に差し替えると、同じコマンドが即座にブロックされ理由文も出た。
  **フックの出力は届いている**
- 差し替えを戻すと再び素通しになる。**落ちているのは `ask` だけ**

つまり "Only the `ask` decision is dropped" という下書きの主張自体は正しい。
外れていたのは「常に」の部分で、実際は**非決定的**。

**上流へ出すときの主張はこうする。** 「v2.1.226 で直った / 直っていない」ではなく
**「同一環境の別セッションで挙動が割れる。フック発火と `deny` の到達は確認済みなので、
`ask` の扱いだけが非決定的」**。これは重複報告になりにくく、原因の絞り込みにも効く。
何がセッション差を生むかは未特定（`permissionMode`・cwd・設定・版・機はすべて同一）。

測り方の注意を二つ、実際に踏んだので記録しておく。

- **対話セッションでしか測れない。** `claude -p`（非対話）は確認を出す相手がいないため
  `ask` を `denied` に倒す。debug ログに `Hook result has permissionBehavior=ask` と
  `Bash tool permission denied` が並んで残る。この `denied` を「直った」と読むと誤る。
  Reproduction 1 の v2.1.226 の行は、人間が対話セッションで目視して埋めた。
- **単独コマンドで撃つ。** 複合コマンド（`probe --check; echo "rc=$?"`）にすると後半が
  `allow` ルールに一致し、素通りが `ask` の不発によるのか `allow` の勝ちによるのか
  切り分けられなくなる。`deny` は `allow` に勝つので、対照側だけが無傷に見えてしまう。

以下は元の下書き。事実と再現手順だけを書き、推測は "Speculation" 節に隔離してある。
コメントとして出したのは Environment / Reproduction / Impact / Workaround の各節を
圧縮したもので、Speculation は載せていない。

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
