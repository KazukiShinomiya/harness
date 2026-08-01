# SESSION_STATE

最終更新: 2026-08-01

## 現在の状況

`guardrails` に保護パス検出を追加し、不可逆操作の判定をトークン境界方式へ書き換えた。
`session-harness` は初版のまま。private リポジトリ `KazukiShinomiya/harness`（master）。

## 前回の戦果

- **誤検出を潰した。** `shlex` によるトークン分割で照合するようにし、
  `echo "git push はまだしない"` や `./confirm -r foo` が発火しなくなったことを確認。
- **保護パス検出を追加した。** `Edit|Write|NotebookEdit` を matcher に取り、`.env`・鍵・
  `.ssh`・`.git`・`dotfiles` 配下への書き込みを拾う。通常のファイルは素通りすることも確認。
- **fail-safe の穴を一つ塞いだ。** 引数なしで `guard.sh` が呼ばれると `exit 2` になり、
  Claude Code がこれを「ブロック」と解釈して全呼び出しを止める状態だった。`ask` に倒すよう修正。
- 環境調査の結果、`/mnt/e`（Windows マウント）では設定ファイルの手編集が file watcher に
  検知されないことを実測した。開発は `~/repos` 側で行うこと。

## 次の行動

1. 実セッションでフックが発火し、`ask` が確認ダイアログとして表示されるところまで確認する。
   スクリプト単体の検証は済んでいるが、実セッションでの表示は未確認のまま。
2. `userConfig` の `multiple: true` がフック環境変数へどう直列化されるか実測する。
3. `~/dotfiles/.claude/settings.json` の drift チェックを修正する（下記メモ参照）。
   dotfiles は `behind 10` のため、着手前に `git -C ~/dotfiles pull` が要る。
4. 実セッションで確認が取れたら、グローバル側の `PreToolUse` と SESSION_STATE 注入分を削除する。

## 決定事項・メモ

- **fail-safe を既定とする。** 判定不能なら素通しでも即ブロックでもなく `ask`。
  判定器は `guard.sh <判定器名>` 経由で呼び、**exit 2 を返さない**（ブロック扱いになるため）。
- **強制力は hooks にしか置けない。** プラグインの `settings.json` は `agent` と
  `subagentStatusLine` の 2 キーのみ。`permissions.deny` は配布できない。
- **drift チェックが空振りしている。** `~/.claude/settings.json` は
  `~/dotfiles/.claude/settings.json` への symlink なので、両者の sha256 は常に一致する。
  SessionStart の drift 警告は原理的に発火しない。比較をやめるか symlink を解くかの判断が要る。
- v2.1.220 の validator は `metadata.pluginRoot` による source 短縮形を拒否する。
