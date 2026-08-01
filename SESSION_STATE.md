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

**再起動直後にこれをやる。** `guardrails@harness` はインストール済み（user スコープ、enabled）。

1. Bash を 1 回打ち、`/tmp/claude-1000/-mnt-e-work-harness/92399dcc-beee-4a56-98f8-42ace5caff1f/scratchpad/guard-probe.log`
   に行が増えるか見る。増えればフックが発火している。
   - 増えた場合: `/tmp/probe/.env` への書き込みで `ask` が画面に出るかまで確認する。
   - 増えない場合: 再起動でも解決しないということ。`/plugin` の Errors タブを見る。
2. 発火が確認できたら、インストール先の診断ログを消す（下記メモ参照）。
3. `claude plugin install guardrails@harness --config extra_patterns=A --config extra_patterns=B` の形で
   `multiple: true` の直列化形式を実測する。
4. 全て確認できたら、グローバル側（`~/dotfiles/.claude/settings.json`）の `PreToolUse` と
   SESSION_STATE 注入分を削除し、dotfiles をコミットする。

## 決定事項・メモ

- **fail-safe を既定とする。** 判定不能なら素通しでも即ブロックでもなく `ask`。
  判定器は `guard.sh <判定器名>` 経由で呼び、**exit 2 を返さない**（ブロック扱いになるため）。
- **強制力は hooks にしか置けない。** プラグインの `settings.json` は `agent` と
  `subagentStatusLine` の 2 キーのみ。`permissions.deny` は配布できない。
- **dotfiles の drift チェックは設計どおり機能している。** `setup.sh` は symlink 運用が正規で
  （`settings.machine.json` を持つ機械だけ実体コピー）、symlink が生きている間に両者が一致するのは
  drift が無いという事実の反映であって検出漏れではない。symlink が外れて実体ファイルに
  置き換わった時に sha256 比較が正しく検出する。**一度これを「空振りするバグ」と誤断したので記録に残す。**
- v2.1.220 の validator は `metadata.pluginRoot` による source 短縮形を拒否する。
- **`/reload-plugins` はプラグインのフックを実行中セッションへ適用しないらしい。** `2 hooks` と
  報告され `plugin list` でも `enabled` なのに、`guard.sh` に仕込んだログが一度も書かれなかった
  （手動実行では書かれるのでログ機構自体は正常）。再起動で解決するかは未確認。
- **インストール先に診断ログを仕込んである。** 確認が済んだら消すこと。
  `~/.claude/plugins/cache/harness/guardrails/0.1.0/scripts/guard.sh` の `set -u` 直後の 1 行。
  リポジトリ側のソースには入っていない。
- `~/.claude/settings.json` は dotfiles への symlink なので、プラグインのインストールで
  **dotfiles 側に未コミット変更が入っている**。移行完了時にまとめてコミットする。
