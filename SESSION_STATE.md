# SESSION_STATE

最終更新: 2026-08-01

## 現在の状況

`guardrails` プラグインは完成しているが、**実セッションでフックが発火しない問題が未解決**。
再起動しても解決しなかった。前回立てた「`/reload-plugins` が実行中セッションに適用されない」
という説では説明がつかないことが判明した（下記）。

`session-harness` は初版のまま。private リポジトリ `KazukiShinomiya/harness`（master）。

## 前回の戦果

- **前回の仮説を否定した。** 再起動後も `guard.sh` の診断ログは 1 行も増えなかった。
  `/reload-plugins` の問題ではない。
- **`/hooks` は正常に登録を報告する。** `6 hooks configured` / `PreToolUse (3)`。
  内訳はグローバル 1 + プラグイン 2 で一致する。**Claude Code はフックを認識している。**
- **プラグイン非経由のフックも発火しない。** `~/.claude/settings.json` に直書きされた
  `PreToolUse`（`git push` 等を部分文字列で拾って `ask` を返す）も動かない。
  `echo "この文字列に git push が含まれる"` を実行しても確認ダイアログが出なかった。
  → **プラグイン固有の問題ではない。**
- 以下は全て正常と確認済み。これらは原因ではない。
  - `settings.json` は valid JSON、symlink（`~/dotfiles/.claude/settings.json`）も生存
  - mtime 19:25:36 < セッション開始 19:32:29（起動後に書き換わった訳ではない）
  - `guard.sh` は実行権限あり、診断ログ行も残存、`hooks.json` の記述も正しい
  - 診断ログの書き込み先ディレクトリは書き込み可能（手動 append は成功する）
  - `claude plugin list` は `guardrails@harness` を user スコープで `enabled` と報告

## 未解決の矛盾（次にここを攻める）

`permissionMode` は `default`、`mode` は `normal`（セッション jsonl から確認）。
`bypassPermissions` ではない。**にもかかわらず、`allow` リストに無い Bash コマンドでも
承認プロンプトが一切出ない。** フックが動かないことと同じ根を持つ可能性が高い。

環境変数に `CLAUDE_CODE_CHILD_SESSION=1` があった。子セッションであることが
権限判定やフック実行に影響している可能性は未検証。

## 次の行動

1. **`claude --debug` で起動し、フック実行のログを見る。** これが最短。
   `~/repos/harness` から起動すること（`/mnt/e` を避ける、SESSION_STATE.md が自動で載る）。
2. 承認プロンプトが出ない件を確定させる。`default` モードなのに `allow` 外が素通りする理由。
3. 原因が判明したら: 診断ログの除去 → `multiple: true` の直列化形式の実測 →
   グローバル側 `PreToolUse` と SESSION_STATE 注入分の削除 → dotfiles をコミット。

## 設計方針の見直し（今回の議論）

**ガードレールを Claude Code の hooks 一層に賭けるのをやめる。** 今回の問題の本質は
「守れなかった」ことより **「守れていないのに黙っていた」** こと。層を分ける。

| 層 | 手段 | 性質 |
|---|---|---|
| OS/FS | パーミッション、`chattr +i` | エージェント無関係に効く。最強 |
| Git | `core.hooksPath` でグローバル hooks | シェル直叩きでも効く。**今の環境でも検証可能** |
| コマンド | `trash-cli` で `rm` を置換 | 不可逆でなくす。確認すら要らない |
| Claude Code | `permissions.deny` / `ask` | 宣言的。hooks より壊れにくい |
| Claude Code | hooks | 柔軟だが今回のように黙って死ぬ |

- **`permissions` は dotfiles 経由で配れる。** 「プラグインからは配れない」ため hooks に
  全部寄せたが、`~/.claude/settings.json` が dotfiles の symlink である以上、配布は解決済み。
  宣言的なぶん hooks より壊れにくいので、動的判定が不要なものは `permissions` に移す。
- **プラグインは「唯一の防壁」から「一番外側の便利層」へ降格する。** 捨てはしない。
  本当に失いたくないものは OS と git の層で守り、プラグインはチーム配布や動的判定用とする。
- **次に着手するなら git hooks 層を勧める。** Claude Code の状態に依存せず、
  今の壊れた環境でもシェルから直接検証できる（「動いたはず」で終わらない）。

## 決定事項・メモ

- **fail-safe を既定とする。** 判定不能なら素通しでも即ブロックでもなく `ask`。
  判定器は `guard.sh <判定器名>` 経由で呼び、**exit 2 を返さない**（ブロック扱いになるため）。
- **強制力は hooks にしか置けない。** プラグインの `settings.json` は `agent` と
  `subagentStatusLine` の 2 キーのみ。`permissions.deny` は*プラグインからは*配布できない。
- **dotfiles の drift チェックは設計どおり機能している。** `setup.sh` は symlink 運用が正規で、
  symlink が生きている間に両者が一致するのは drift が無いという事実の反映。
  **一度これを「空振りするバグ」と誤断したので記録に残す。**
- v2.1.220 の validator は `metadata.pluginRoot` による source 短縮形を拒否する。
- **インストール先に診断ログを仕込んである。** 確認が済んだら消すこと。
  `~/.claude/plugins/cache/harness/guardrails/0.1.0/scripts/guard.sh` の `set -u` 直後の 1 行。
  リポジトリ側のソースには入っていない。出力先は絶対パス指定で、セッションを跨いでも同じ:
  `/tmp/claude-1000/-mnt-e-work-harness/92399dcc-beee-4a56-98f8-42ace5caff1f/scratchpad/guard-probe.log`
  （現在 2 行。1 行目は手動実行、2 行目は書き込み可否の確認。**フック由来の行は 0**）
- `~/.claude/settings.json` は dotfiles への symlink なので、プラグインのインストールで
  **dotfiles 側に未コミット変更が入っている**。移行完了時にまとめてコミットする。
- **起動は必ず `~/repos/harness` から。** 今回 `/mnt/e/work/harness` で起動したため
  SESSION_STATE.md が読み込まれず、前回の経緯を引き継げなかった。
  復元はセッションログ（`~/.claude/projects/-mnt-e-work-harness/*.jsonl`）から可能。
