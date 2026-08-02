# SESSION_STATE

最終更新: 2026-08-02

## 現在の状況

多層防御が三層とも稼働している。private リポジトリ `KazukiShinomiya/harness`（master）。
harness / dotfiles とも push 済み、作業ツリーはクリーン。

**`ask` という経路そのものが機能しない**（Claude Code v2.1.220）。PreToolUse フック経由でも
`permissions` の `ask` ルールでも確認が出ず、`deny` は両経路とも効く。対照実験で確定した。
こちらでは直せないため、確実に止めたいものは `deny` と git 層へ寄せてある。
再現手順と対照は README と `docs/upstream-report-draft.md` に。

## 前回の戦果

**「実セッションでフックが発火しない」という 2 セッション分の前提は誤りだった。取り消す。**
フックは最初から発火していた。誤診の原因は計測器の置き場所——マーケットプレイスが
`directory` source のときプラグインはキャッシュではなくリポジトリから直接読まれるのに、
診断ログをキャッシュ側に仕込んでいた。加えてログの出力先ディレクトリも消えており、
`|| true` が書き込み失敗を握り潰していた。二重に見えなくなっていた。

この日の実装（詳細は README と git log）:

- `guardrails` / `session-harness` の自己診断。登録の有無ではなく**実際に動くか**を毎回検査し、
  異常なら `systemMessage` と `additionalContext` の両方で報告する
- `githooks/` — Claude Code 非依存の git 層。**グローバル適用済み**
- `permissions/` — `deny` 雛形と差分マージ用 `apply.py`
- `install.sh` / `tests/run.sh`（32 項目、副作用なし）
- LICENSE（MIT）、上流報告の下書き

**自分が「黙って壊す」側になっていたのを最後に見つけた。** `core.hooksPath` はそのディレクトリ
しか見ないため、実装していない種類の hook（`commit-msg` 等）が警告も無く無効化される。
受け渡し専用の hook を 14 種類ぶん置いて塞いだ。テストで回帰を見張っている。

## 次の行動

1. **`docs/upstream-report-draft.md` を提出するか判断する。** 下書きは完成。外向きの公開行為。
2. **public への切り替え。** 準備は全て済んでいる。残るのは可視性を変える操作そのもの。
3. OS/FS 層（`chattr +i`）と `trash-cli` による `rm` 置換。未着手。
   `chattr` は deny に入れたので設定は手動になる。
4. `userConfig` の `multiple: true` が hook 環境変数へどう直列化されるか未検証。

## この機の適用状態

| 層 | 状態 |
|---|---|
| プラグイン | `guardrails` `session-harness` とも user スコープで有効 |
| `permissions.deny` | 12 件（ディスク破壊系 8 + 電源系 4）。`sudo` と設定ファイル保護は**入れていない** |
| git 層 | `core.hooksPath` をグローバル適用。`harness` には `--local` も残してある |

撤回はいずれも一手（`githooks/install.sh --uninstall`、`deny` は dotfiles の履歴から）。

## 決定事項・メモ

- **黙らないことと止めることは別。** 危険でないものを止める必要は無いが、黙ってよいわけでもない。
  `session-harness` は失敗も不在も報告するが、止めはしない。
- **fail-safe の既定は `ask` のまま。** `deny` にすると判定器が壊れた瞬間に作業不能になる。
  既定を硬くするのではなく「黙っているのをやめる」方向で解いた。
- **層ごとに得意な粒度が違う。** `permissions.deny` はコマンド名単位、git 層は引数・内容単位、
  プラグインは動的判定。同じことを複数層でやろうとしない。
- **判定器は `guard.sh` 経由で呼び、exit 2 を返さない**（ブロック扱いになるため）。
- **導入は手順ゼロにできない。** プロジェクトスコープの `extraKnownMarketplaces` は効かない（実測）。
- **`githooks` の保護パターンと `protected_paths.py` は意図的に重複させてある。**
  片方を変えたらもう片方も見ること。`tests/run.sh` が主要パターンの両層存在を確認する。
- **変更したら `tests/run.sh` を通すこと。** 使い捨てのコマンドで確認して終わりにしない。
- v2.1.220 の validator は `metadata.pluginRoot` による source 短縮形を拒否する。
- **起動は必ず `~/repos/harness` から。** `/mnt/e/work/harness` で起動すると SESSION_STATE が
  読み込まれない（`session-harness` が「どこを探したか」を報告するので気付ける）。
