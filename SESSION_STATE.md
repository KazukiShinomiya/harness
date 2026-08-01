# SESSION_STATE

最終更新: 2026-08-02

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
- **`Write` でも発火しない（強い証拠）。** `/tmp/probe/.env` への `Write` を実行しても
  診断ログは 1 行も増えなかった。matcher `Edit|Write|NotebookEdit` は保護パス検出を呼ぶはずで、
  かつ `Write` は read-only ではないため、下記の `echo` の落とし穴に該当しない。
  **これが現時点で最も確度の高い観測。**
- **プラグイン非経由のフックも発火しない。** `~/.claude/settings.json` に直書きされた
  `PreToolUse`（`git push` 等を部分文字列で拾って `ask` を返す）も動かない。
  ただしこの検証には `echo "... git push ..."` を使ってしまった。**README の「落とし穴」に
  自分で書いたとおり、`echo` は組み込みの read-only コマンドなのでフックの結果に関わらず
  確認が出ない。この一件については証拠として無効。**やり直すこと。
  → プラグイン固有の問題ではない、という結論自体は上の `Write` の観測から支持される。
- 以下は全て正常と確認済み。これらは原因ではない。
  - `settings.json` は valid JSON、symlink（`~/dotfiles/.claude/settings.json`）も生存
  - mtime 19:25:36 < セッション開始 19:32:29（起動後に書き換わった訳ではない）
  - `guard.sh` は実行権限あり、診断ログ行も残存、`hooks.json` の記述も正しい
  - 診断ログの書き込み先ディレクトリは書き込み可能（手動 append は成功する）
  - `claude plugin list` は `guardrails@harness` を user スコープで `enabled` と報告

## 未解決の矛盾（次にここを攻める）

`permissionMode` は `default`、`mode` は `normal`（セッション jsonl から確認）。
`bypassPermissions` ではない。にもかかわらず、`allow` リストに無い Bash コマンドでも
承認プロンプトが出なかった——**ただしこれは正常な可能性がある。** 当日打ったコマンドは
`ls` `cat` `grep` `find` `stat` `wc` 等ほぼ全て read-only 系で、Claude Code がそう判定して
権限確認を省いたのなら `default` と矛盾しない。**この「矛盾」は矛盾ではないかもしれない。**

一方で `Write` は read-only ではない。`/tmp/probe/.env` への `Write` が承認プロンプトを
出したかどうかは未確認のまま（ユーザーに尋ねていない）。**次回まずここを確かめること。**
出ていたなら権限系は正常で、フック実行だけが飛んでいることになる。

環境変数に `CLAUDE_CODE_CHILD_SESSION=1` があった。子セッションであることが
権限判定やフック実行に影響している可能性は未検証。

## 次の行動

0. **検証は必ず README の「実セッションでの検証手順」に従うこと。** 今回、そこに自分で
   書いた落とし穴（`echo` で試すな）を踏んで一手無駄にした。`/tmp/probe/.env` への
   `Write` が最もクリーンな検証。
1. **`claude --debug` で起動し、フック実行のログを見る。** これが最短。
   `~/repos/harness` から起動すること（`/mnt/e` を避ける、SESSION_STATE.md が自動で載る）。
2. `Write` 実行時に承認プロンプトが出るかをユーザーに確認する。権限系が生きているかの切り分け。
3. 原因が判明したら: 診断ログの除去 → `multiple: true` の直列化形式の実測 →
   グローバル側 `PreToolUse` と SESSION_STATE 注入分の削除 → dotfiles をコミット。

## 今後の3本柱

フック問題の解決を全ての前段に置く。動かないものは配れないし公開もできない。
逆にあれが片付けば残りは素直に進む。

### 1. 他リポジトリへの展開（手順の説明と簡易化）

現状でも他人向けは 2 コマンドで済む。

```bash
claude plugin marketplace add KazukiShinomiya/harness
claude plugin install guardrails@harness --scope project
```

**手順ゼロにできる可能性を先に検証する。** グローバル設定で使っている
`extraKnownMarketplaces` が**プロジェクトの `.claude/settings.json` でも効くなら**、
marketplace 定義と `enabledPlugins` を対象リポジトリにコミットするだけで、
clone した人は何もしなくてよくなる。効かなければ `install.sh` でワンライナー化に落とす。
検証一発で分岐するので、ここから手を付けるのが早い。

### 2. ハーネスの充実

**最優先は「ガードレールの自己診断」。** 今回の一件がそのまま理由になる。
黙って消えるガードレールは、自分用なら「おかしいな」で済むが、**配布すると害になる**。
守られていると思わせて守っていないのは、何も無いより悪い。

`SessionStart` で生存を確認し、死んでいれば起動時に警告する。
**要件定義は今回の手作業デバッグがそのまま使える**——登録されているか / 実行されるか /
ログが書けるか。以降は多層防御の git hooks 層、`permissions` 雛形の提供と続く。

### 3. 公開準備

| 項目 | 状況 |
|---|---|
| `.gitignore` | 問題なし（`__pycache__` は追跡されていないと確認済み） |
| `SESSION_STATE.md` | **要判断。** 個人の作業ログで絶対パスや環境事情が入る。公開対象から外すか整理するか |
| README の `<owner>` | 実名に置換する |
| LICENSE | 未設置 |
| 動作検証 | **未完了。ここが最大の障害** |

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
