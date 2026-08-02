# SESSION_STATE

最終更新: 2026-08-02

## 現在の状況

多層防御が**四層**になった。private リポジトリ `KazukiShinomiya/harness`（master）。
`tests/run.sh` は 56 項目すべて成功。

**`ask` という経路そのものが機能しない**（Claude Code v2.1.220）。PreToolUse フック経由でも
`permissions` の `ask` ルールでも確認が出ず、`deny` は両経路とも効く。対照実験で確定した。
こちらでは直せないため、確実に止めたいものは `deny` と git 層へ寄せてある。

| 層 | 状態 |
|---|---|
| プラグイン | `guardrails` `session-harness` とも user スコープで有効 |
| `permissions.deny` | 12 件（ディスク破壊系 8 + 電源系 4）。`sudo` と設定ファイル保護は**入れていない** |
| git 層 | `core.hooksPath` をグローバル適用。`harness` には `--local` も残してある |
| OS/FS 層 | **実装済み・この機へは未適用。** `trash-cli` の導入に sudo が要る |

## 前回の戦果

**積み残し 4 件のうち 3 件を片付けた。残るは public 化（君の判断）だけ。**

- **`userConfig` の `multiple: true` はカンマ区切りだった。** 本体バイナリの
  `M[CLAUDE_PLUGIN_OPTION_<KEY>] = String(値)` を読み、子セッション（`claude -p`）を
  起こして生バイトで裏を取った。`_common.option_list()` をそれに合わせて単純化。
  副産物として二つ判明——**設定は新セッションでしか読まれない**（実行中のセッションには
  届かない）、**プロジェクトスコープの `pluginConfigs` は効かない**（`extraKnownMarketplaces`
  と同じ穴）
- **OS/FS 層 `osfs/` を追加。** `rm-guard`（`~/.local/bin/rm` に置く `rm` の置き換え。
  消さずにゴミ箱へ送る）と `immutable.sh`（`chattr +i` の候補提示。既定では何も適用しない）。
  alias では非対話シェルに届かないことを実測したうえで PATH 前方に置く形にした
- **上流報告は新規 issue を立てず、既存 [#79356](https://github.com/anthropics/claude-code/issues/79356)
  へコメントした。** 提出前に検索したら同じ報告が 15 件以上あった。あちらは Windows /
  PowerShell 報告で `platform:windows` ラベルが付いていたので、Linux / Bash / v2.1.220 でも
  再現することを対照実験ごと足した。[投稿](https://github.com/anthropics/claude-code/issues/79356#issuecomment-5157316941)
- テストを 32 → 56 項目へ（userConfig の直列化 5、osfs 19）

## 次の行動

1. **public への切り替え。** 準備は全て済んでいる。残るのは可視性を変える操作そのもの。
   外向きの行為なので君が決めること。
2. **OS/FS 層をこの機へ適用する。** `sudo` が要るので手で叩くこと:
   `sudo apt install trash-cli && osfs/install.sh`。`osfs/install.sh --status` で現況が見える。
   `chattr +i` は代償が重いので `osfs/immutable.sh status` を読んでから選ぶ。
3. `session-harness` は初版のまま手付かず。

## 決定事項・メモ

- **黙らないことと止めることは別。** 危険でないものを止める必要は無いが、黙ってよいわけでもない。
  `session-harness` は失敗も不在も報告するが、止めはしない。
- **OS/FS 層だけ思想が違う。止めずに取り消せるようにする。** `rm` は日常的に使うので確認を
  挟むと長続きしない。消えたものが戻せるなら止める必要がない。
- **ゴミ箱が使えないとき `rm-guard` は本物の `rm` へ落とさず止まる。** 落とすと「守られている
  つもりで守られていない」状態が黙って続く。このリポジトリが潰そうとしている失敗そのもの。
- **fail-safe の既定は `ask` のまま。** `deny` にすると判定器が壊れた瞬間に作業不能になる。
- **層ごとに得意な粒度が違う。** `permissions.deny` はコマンド名単位、git 層は引数・内容単位、
  プラグインは動的判定、OS/FS 層は呼び出し元を問わない。同じことを複数層でやろうとしない。
- **判定器は `guard.sh` 経由で呼び、exit 2 を返さない**（ブロック扱いになるため）。
- **導入は手順ゼロにできない。** プロジェクトスコープの `extraKnownMarketplaces` は効かない（実測）。
- **`githooks` の保護パターンと `protected_paths.py` は意図的に重複させてある。**
  片方を変えたらもう片方も見ること。`tests/run.sh` が主要パターンの両層存在を確認する。
- **変更したら `tests/run.sh` を通すこと。** 使い捨てのコマンドで確認して終わりにしない。
- v2.1.220 の validator は `metadata.pluginRoot` による source 短縮形を拒否する。
- **起動は必ず `~/repos/harness` から。** `/mnt/e/work/harness` で起動すると SESSION_STATE が
  読み込まれない（`session-harness` が「どこを探したか」を報告するので気付ける）。
- **Claude Code は `.claude/settings.local.json` をメモリ上の設定で書き戻す。** 実験で入れた
  `pluginConfigs` を消しても、権限追加のタイミングで復活した。実験値は最後に必ず確認して消すこと。
