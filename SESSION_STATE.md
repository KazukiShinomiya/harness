# SESSION_STATE

最終更新: 2026-08-02

## 現在の状況

**「実セッションでフックが発火しない」という前提は誤りだった。取り消す。**
フックは最初から正常に発火していた。切り分けが完了し、`guardrails` に自己診断
（`SessionStart`）を実装した。private リポジトリ `KazukiShinomiya/harness`（master）。

残る問題は一点のみ: **PreToolUse フックの `ask` が確認ダイアログとして表示されない。**
`deny` は同一経路で確実に効く。フック機構は健全で、`ask` の扱いだけが飛んでいる。

## 前回の戦果

### 誤診の原因（2 セッション溶かした）

1. **計測器を実行されないファイルに置いていた。** `extraKnownMarketplaces` が `harness` を
   `directory` source（`~/repos/harness`）で登録しているため、プラグインはキャッシュではなく
   **リポジトリから直接**読まれる。診断ログは `~/.claude/plugins/cache/.../guard.sh` に
   仕込んであったので、当然一行も増えなかった。
   フック実行時の `CLAUDE_PLUGIN_ROOT=/home/ubuntu/repos/harness/plugins/guardrails` で確定。
2. **その診断ログの出力先も消えていた。** 前セッションの scratchpad ごと消滅し、
   `>> ... 2>/dev/null || true` が書き込み失敗を握りつぶしていた。二重に見えなくなっていた。

前セッションの「`Write` でも発火しない（最も確度の高い観測）」は、この二重の盲点によるもの。

### 実測で確定した切り分け

| 段 | 状態 | 根拠 |
|---|---|---|
| フックの登録 | ✓ | `/hooks` が 6 hooks / PreToolUse (3) を報告 |
| フックスクリプトの実行 | ✓ | 出力先を修正した診断ログに実際に行が増えた |
| 判定器の出力 | ✓ | フック経由の stdout に正しい `ask` JSON（`OUT=` 行で実測） |
| `deny` の反映 | ✓ | `sed 's/"ask"/"deny"/'` を挟むとブロックされ理由文も表示 |
| **`ask` の反映** | **✗** | 同一経路・同一 JSON で `ask` のときだけ素通し |

`permissionMode` は `default` / `acceptEdits` の両方で再現。**モード非依存。**
公式ドキュメント（permissions の "Extend permissions with hooks"）は `ask` について
"force a prompt" と書いており、**観測は仕様と食い違う**。v2.1.220。

`CLAUDE_CODE_CHILD_SESSION=1` は容疑者から外れた。claude 本体（pid）の環境にも親 zsh にも
存在せず、Claude Code が Bash ツールの子プロセスへ注入しているマーカーにすぎない。

### 実装したもの

- `plugins/guardrails/scripts/selfcheck.py` / `selfcheck.sh`（新規）
  `SessionStart` で `guard.sh` を合成ペイロードで実際に起動し、判定器が決定を返すところまで
  通しで検査する。異常なら `systemMessage` でユーザーに、`additionalContext` で Claude に警告。
  診断自体が失敗しても黙らず「生死不明」と報告する。正常時も**実行中のプラグインパスを毎回報告**
  （今回の誤診はこれ一つで防げた）。異常系 2 通り（root 未設定 / 判定器が黙る）を実測で確認済み。
- `plugins/guardrails/hooks/hooks.json` に `SessionStart` エントリを追加
- README に「`ask` は環境によって黙って消える（実測）」「自己診断」の 2 節、
  落とし穴に 2 項（`directory` source / 診断ログの出力先）を追記。TODO を実測結果で更新
- `claude plugin validate` は marketplace / plugin とも通過

**既定 decision は `ask` のまま据え置いた**（ユーザー判断）。`deny` は判定器が壊れた瞬間に
全プロジェクトで作業不能になり fail-safe 方針の撤回になるため、既定を硬くするのではなく
「黙っているのをやめる」方向で解いた。

### 多層防御の git 層（新規）

`githooks/` を実装した。プラグインではなく `core.hooksPath` に載せる素の git フックで、
**Claude Code の状態に一切依存しない。** `ask` が消える問題があっても独立して効く。

- `pre-commit` — 秘密情報（`.env` / `*.pem` / `*.key` / `*credentials*` 等）のコミットを止める
- `pre-push` — 保護ブランチへの強制 push と削除を止める（既定 `main` `master`）
- `_lib.sh` — 保護パターン、`chain_local_hook`（`core.hooksPath` が `.git/hooks` を潰す問題への対処）
- `install.sh` — `--local` / `--uninstall` 対応。既存の `core.hooksPath` は上書きせず exit 1

**git フックには問い返す手段が無いので `ask` に倒せない。止める層。** 逃げ道は `--no-verify` のみ。

隔離環境（`HOME` ごと差し替え）で 7 通り実測済み: 通常コミット○ / `.env` コミット✗ /
`--no-verify`○ / 通常 push○ / 強制 push✗ / ブランチ削除✗ / ローカルフック委譲○ /
保護外ブランチの強制 push○（誤爆なし）。**ユーザーのグローバル git 設定には触れていない。**

## 次の行動

1. **未コミット変更のレビューとコミット。** `~/repos/harness`（selfcheck 一式・`githooks/` 一式・
   README・hooks.json）と `~/dotfiles`（プラグインのインストールで settings.json に入った差分）。
2. **`githooks/install.sh` を実環境へ適用するか決める。** `core.hooksPath` は**全リポジトリ**に効き、
   `.git/hooks` を無効化する（委譲で対処済みだが影響範囲は広い）。まず `--local` で
   `~/repos/harness` 自身に入れて使い心地を見るのが安全。
3. **自己診断を実セッションで確認する。** `~/repos/harness` から起動し直し、
   起動時に `guardrails: 有効（...）` が Claude 側の文脈に入るかを見る。
   壊した複製を `CLAUDE_PLUGIN_ROOT` に食わせる検証は済んでいるが、実セッションは未確認。
4. `permissions` の `ask` **ルール**（フックではなく設定側）が表示されるか検証。
   表示されるなら、動的判定の要らないものは `permissions` へ移して確実に止められる。
   残る層の中で最も費用対効果が高い。
5. `ask` の件を上流へ報告するか判断する。再現手順は README に揃っている。

## 今後の3本柱

### 1. 他リポジトリへの展開

現状でも他人向けは 2 コマンド。

```bash
claude plugin marketplace add KazukiShinomiya/harness
claude plugin install guardrails@harness --scope project
```

**手順ゼロにできるか未検証。** グローバルで使っている `extraKnownMarketplaces` が
プロジェクトの `.claude/settings.json` でも効くなら、marketplace 定義と `enabledPlugins` を
対象リポジトリにコミットするだけで済む。効かなければ `install.sh` でワンライナー化。

### 2. ハーネスの充実

自己診断と git 層は実装した。残りは `permissions` 雛形の提供（dotfiles 経由で配れる）。
OS/FS 層（`chattr +i`）と `trash-cli` による `rm` の置換はまだ手付かず。

### 3. 公開準備

| 項目 | 状況 |
|---|---|
| `.gitignore` | 問題なし |
| `SESSION_STATE.md` | **要判断。** 個人の作業ログで絶対パスが入る。公開対象から外すか整理するか |
| README の `<owner>` | 実名に置換する |
| LICENSE | 未設置 |
| 動作検証 | フック発火は確認済み。`ask` 非表示という既知の制約つきで公開可能な状態 |

## 設計方針（層を分ける）

ガードレールを Claude Code の hooks 一層に賭けない。今回の問題の本質は「守れなかった」ことより
**「守れていないのに黙っていた」** こと。自己診断はそれに対する直接の回答。

| 層 | 手段 | 性質 |
|---|---|---|
| OS/FS | パーミッション、`chattr +i` | エージェント無関係に効く。最強 |
| Git | `core.hooksPath` でグローバル hooks | **実装済み（`githooks/`）。** シェル直叩きでも効く |
| コマンド | `trash-cli` で `rm` を置換 | 不可逆でなくす。確認すら要らない |
| Claude Code | `permissions.deny` / `ask` | 宣言的。hooks より壊れにくい（`ask` の表示は要検証） |
| Claude Code | hooks | 柔軟。`deny` は確実、`ask` は環境依存 |

`permissions` は dotfiles 経由で配れる（`~/.claude/settings.json` が symlink のため）。
プラグインからは配れないが、配布経路としては解決済み。

## 決定事項・メモ

- **fail-safe を既定とする。** 判定不能なら `ask`。判定器は `guard.sh <判定器名>` 経由で呼び、
  **exit 2 を返さない**（ブロック扱いになるため）。
- **強制力は hooks にしか置けない。** プラグインの `settings.json` は `agent` と
  `subagentStatusLine` の 2 キーのみ。`permissions.deny` は*プラグインからは*配布できない。
- **dotfiles の drift チェックは設計どおり機能している。** 一度これを誤断したので記録に残す。
- v2.1.220 の validator は `metadata.pluginRoot` による source 短縮形を拒否する。
- **診断ログは撤去済み。** リポジトリ側・キャッシュ側の `guard.sh` は一致し、probe 行は残っていない。
- **起動は必ず `~/repos/harness` から。** `/mnt/e/work/harness` で起動すると SESSION_STATE.md が
  読み込まれない。今回もそこで起動して危うく経緯を失うところだった
  （復元はセッションログ `~/.claude/projects/-mnt-e-work-harness/*.jsonl` から可能）。
