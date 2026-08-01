# harness

各プロジェクトへハーネスとガードレールを撒くための Claude Code プラグイン集。
このリポジトリ自体がマーケットプレイスを兼ねる。

## 収録プラグイン

| プラグイン | 役割 | 強制力 |
|---|---|---|
| `guardrails` | 不可逆操作（commit/push/reset/rm 等）と保護パスへの書き込みの前に確認を挟む | あり（PreToolUse hook） |
| `session-harness` | `SESSION_STATE.md` の読み込みと更新運用 | なし（hook による文脈注入 + skill） |

責務で分けてある。ガードレールだけ欲しい相手にセッション運用まで押し付けないため。

## 開発中の動作確認

インストールせずに読み込める。

```bash
claude --plugin-dir ~/repos/harness/plugins/guardrails
claude --plugin-dir ~/repos/harness/plugins/guardrails --plugin-dir ~/repos/harness/plugins/session-harness
```

編集後は `/reload-plugins` で再読込。検証は次のとおり。

```bash
claude plugin validate ~/repos/harness                        # marketplace.json
claude plugin validate ~/repos/harness/plugins/guardrails     # plugin.json
claude plugin validate ~/repos/harness/plugins/session-harness
```

なおドキュメントには `metadata.pluginRoot` を置けば `"source": "guardrails"` と短縮できるとあるが、
v2.1.220 の validator はこれを `Invalid input` で弾く。`"./plugins/guardrails"` と明示している。

## インストール

```bash
# 自分用（ローカルパスから）
claude plugin marketplace add ~/repos/harness
claude plugin install guardrails@harness

# 他人・チーム用（GitHub 公開後）
claude plugin marketplace add <owner>/harness
claude plugin install guardrails@harness --scope project
```

`--scope project` はリポジトリの `.claude/settings.json` に `enabledPlugins` を書き、clone した全員へ届く。
ただしプロジェクトスコープは workspace trust の承認を経てから読み込まれ、background monitors は読み込まれない。

## 設計上の決定

### fail-safe（判定不能なら ask）

`guardrails` の判定器が動かない・落ちた場合、素通し（fail-open）にはせず確認ダイアログへ倒す。

- **fail-open** はガードレールとして意味を成さない。壊れていることに気付けない。
- **fail-close（deny）** は判定器が壊れた瞬間に全プロジェクトで作業不能になる。
- したがって既定は **ask**。人間が判断すれば進める。

`userConfig.decision` を `deny` にすれば即ブロックへ切り替えられる。

### プラグインの settings.json では permissions を配れない

Claude Code のプラグインが `settings.json` で供給できるのは `agent` と `subagentStatusLine` の 2 キーのみ。
`permissions.deny` は配布できないため、強制力はすべて hooks に寄せてある。

### 判定はトークン境界で行う

`irreversible_ops.py` は部分文字列一致ではなく `shlex` でトークン分割してから照合する。
`echo "git push はまだしない"` のように引用符の中にパターンが現れるだけの文字列で発火させないため。
コマンドが解釈できない（クォート不整合など）場合は例外を上げて非 0 で終了し、`guard.sh` が `ask` に倒す。

### 判定器は guard.sh 経由で呼ぶ

`hooks.json` は判定器を直接呼ばず、必ず `guard.sh <判定器名>` の形で呼ぶ。
`guard.sh` は python の不在・判定器の異常・引数の欠落のいずれでも `ask` を返して exit 0 する。

**exit 2 を返してはいけない。** Claude Code は exit 2 を「ツール呼び出しをブロック」と解釈するため、
設定ミスで全呼び出しが止まる。fail-safe 方針と正面から矛盾する。

### 状態の置き場所

`${CLAUDE_PLUGIN_ROOT}` はプラグイン更新のたびに変わる。永続させたいものは `${CLAUDE_PLUGIN_DATA}` へ。
現状どちらのプラグインも状態を持たない。

## 既存のグローバル設定からの移行

`~/.claude/settings.json` の `hooks` には、ここへ移植した内容と同等のものが残っている。
両方が有効なあいだは **確認が二重に出る**。`guardrails` を有効化して動作を確認したら、
グローバル側の `PreToolUse` / `SessionStart`（SESSION_STATE 注入分）を削除すること。

なお `~/.claude/settings.json` の正本は `~/dotfiles/.claude/settings.json` 側にあるため、
削除は dotfiles 側で行い同期する。

## 開発環境上の注意（WSL2）

**`/mnt/e` などの Windows マウント配下で作業しない。** drvfs は inotify を通さないため、
設定ファイルの手編集が Claude Code の file watcher に検知されない。`.claude/settings.local.json` に
hooks を書き足しても `/hooks` に現れず、さらに Claude Code 自身が同ファイルへ書き込んだ時点で
手編集が消える。実測で確認済み。開発は WSL ネイティブ側（`~/repos`）で行うこと。

## TODO

- [ ] `userConfig` の `multiple: true` が hook 環境変数へどう直列化されるか未検証
      （`_common.option_list()` は JSON 配列・改行区切り・カンマ区切りの三通りを受けるようにしてある）
- [ ] 実セッションでフックが発火し、`ask` が確認ダイアログとして表示されるところまで未確認
      （スクリプト単体の検証は済んでいる）
