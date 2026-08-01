# SESSION_STATE

最終更新: 2026-08-01

## 現在の状況

骨組みが完成し、private リポジトリ `KazukiShinomiya/harness` へ push 済み（`1e53263`、master）。
`guardrails` と `session-harness` の 2 プラグインが `claude plugin validate` を通っている。
まだ実セッションでのフック発火は未確認。

## 前回の戦果

- スクリプト単体での検証は全て通した。危険コマンド検出、安全コマンドの素通し、
  `extra_patterns` の追加、`decision=deny` への切り替え、状態ファイルの注入。
- fail-safe を破壊試験で確認した。判定器を構文エラーにした場合と python 不在の場合、
  どちらも `ask` に fallback する。

## 次の行動

1. `claude --plugin-dir ~/repos/harness/plugins/guardrails` を対話起動し、
   実セッションでフックが発火するか確認する。
2. `userConfig` の `multiple: true` がフック環境変数へどう直列化されるか実測する。
   `irreversible_ops.py` は三通りを受けるようにしてあるが、どれが正しいか未確認。
3. 検出パターンの誤検出を精査する。特に `rm -r` の部分文字列一致。
4. 実セッションで確認が取れたら、グローバル `~/.claude/settings.json` 側の
   `PreToolUse` と SESSION_STATE 注入分を削除する（`~/dotfiles` が正本）。

## 決定事項・メモ

- **fail-safe を既定とする。** 判定不能なら素通し（fail-open）でも即ブロック（fail-close）でもなく
  `ask`。壊れたときに全プロジェクトが止まるのを避けつつ、素通しも防ぐため。
- **強制力は hooks にしか置けない。** プラグインの `settings.json` は `agent` と
  `subagentStatusLine` の 2 キーのみ。`permissions.deny` は配布できない。
- **プラグインは責務で分ける。** ガードレールだけ欲しい相手にセッション運用を押し付けない。
- v2.1.220 の validator は `metadata.pluginRoot` による source 短縮形を拒否する。
  ドキュメントの記述と食い違うため `./plugins/<name>` と明示している。
