# harness

各プロジェクトへハーネスとガードレールを撒くための道具立て。
このリポジトリ自体がマーケットプレイスを兼ねる。

| ディレクトリ | 層 | 効く範囲 |
|---|---|---|
| `plugins/` | Claude Code プラグイン | 動的判定とチーム配布。`deny` は効くが `ask` は環境依存 |
| `permissions/` | Claude Code の `permissions.deny` | 宣言的で確実。コマンド名単位の粗い粒度 |
| `githooks/` | 素の git フック | **Claude Code 非依存。** 引数レベルの判定が得意 |

**一層に賭けない。** プラグイン側の強制力は Claude Code の実装に左右される（実際、`ask` が
黙って表示されなくなる事例に当たった）。本当に失いたくないものは git 層で守り、
プラグインは動的判定とチーム配布のための一番外側の層として扱う。

## 収録プラグイン

| プラグイン | 役割 | 強制力 |
|---|---|---|
| `guardrails` | 不可逆操作（commit/push/reset/rm 等）と保護パスへの書き込みの前に確認を挟む | 条件付き（PreToolUse hook。既定の `ask` が表示されない環境では素通しになる。[詳細](#ask-は環境によって黙って消える実測)） |
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

## 実セッションでの検証手順

```bash
cd ~/repos/harness
claude --plugin-dir ~/repos/harness/plugins/guardrails
```

`/hooks` を開くと `Plugin Hooks` として 2 件（`Bash` と `Edit|Write|NotebookEdit`）が並ぶ。

| # | 指示 | 期待 |
|---|---|---|
| 1 | `/tmp/probe/.env` に `FOO=bar` と書かせる | `guardrails: protected path (.env): ...` |
| 2 | `git -C /tmp/probe commit --dry-run` を実行させる | `guardrails: irreversible op (git commit): ...` |
| 3 | `ls -la /tmp` を実行させる | 何も出ない |

**ただし v2.1.220 では 1・2 の確認そのものが表示されない**（[詳細](#ask-は環境によって黙って消える実測)）。
「期待」の列は `ask` が正しく扱われる環境でのもの。現状この手順で確認が出なくても、
フックが死んでいるとは限らない。フックが動いているかは起動時の自己診断が報告する。
判定器が決定を返しているかを直接見たいなら、フックを介さず単体で叩くのが確実:

```bash
cd ~/repos/harness/plugins/guardrails/scripts
echo '{"tool_name":"Bash","tool_input":{"command":"rm -f /tmp/x"}}' | python3 ./irreversible_ops.py
```

1 が最もクリーンな検証になる。`Edit`/`Write` を見ているのは guardrails だけで、
移行前のグローバルフックは `Bash` しか matcher に持たないため、確認が出れば guardrails 由来と確定できる。
2 は両方が発火して二重になるが、文言が違う（グローバル側は `irreversible op (commit/push/deploy/reset/rm):`）ので見分けられる。

### 落とし穴

- **`echo` や `true` で試さない。** 組み込みの read-only コマンドなので、フックの結果に関わらず確認が出ない
- **`/mnt/e` で起動しない。** file watcher が効かず、編集が `/reload-plugins` に拾われない
- **マーケットプレイスが `directory` source なら、キャッシュ側は実行されない。**
  `~/.claude/settings.json` の `extraKnownMarketplaces` が `{"source":"directory","path":"..."}`
  でこのリポジトリを指している場合、プラグインは `~/.claude/plugins/cache/...` ではなく
  **リポジトリから直接**読まれる。キャッシュ側を編集しても何も起きない。
  実行中の実体は `CLAUDE_PLUGIN_ROOT` が指すパスであり、自己診断が毎回それを報告する。
  これを取り違えて「フックが発火しない」と 2 セッション誤診した
- **診断ログの出力先はセッションを跨いで生存するパスにする。** scratchpad はセッション終了時に
  消える。`>> ... 2>/dev/null || true` と併せると、書き込み失敗が握りつぶされて
  「ログが増えない = フックが動いていない」と誤読する
- 起動時に `userConfig` の入力を求められるかを見ておく。求められるなら `extra_patterns` に
  値を 2 つ入れることで、`multiple: true` の直列化形式（TODO）もそのまま確認できる

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

## git 層のガードレール（Claude Code 非依存）

`githooks/` はプラグインではない。`core.hooksPath` に載せる素の git フックで、
**Claude Code が動いていなくても、別のエージェントが動かしても、シェルから直接叩いても効く。**
プラグイン側の `ask` が黙って消えるような事故があっても、この層は独立して生きている。

```bash
githooks/install.sh            # 全リポジトリ
githooks/install.sh --local    # カレントのリポジトリだけ（試すとき）
githooks/install.sh --uninstall
```

| フック | 止めるもの | 逃げ道 |
|---|---|---|
| `pre-commit` | 秘密情報（`.env` / `*.pem` / `*.key` / `*credentials*` 等）のコミット | `git commit --no-verify` |
| `pre-push` | 保護ブランチへの**強制 push** と**削除**（既定 `main` `master`） | `git push --no-verify` |

```bash
git config guardrails.protectedBranches "main master release"
git config guardrails.disable true      # このリポジトリでは切る
```

### ここは ask に倒さない

プラグイン側の判定器は fail-safe で `ask` に倒すが、git フックには**ユーザーへ問い返す手段が無い**。
標準入力は git が使っており、確認ダイアログも出せない。したがってこの層は「確認を挟む」のではなく
**止める**。代わりに逃げ道を `--no-verify` という明示的な一手に限定してある。
事故で通ることはないが、意図があれば通る。

### `core.hooksPath` はリポジトリ固有のフックを無効にする

これが唯一の副作用で、無視できない。`core.hooksPath` を設定すると `.git/hooks/` が丸ごと
読まれなくなり、husky や lefthook を使っているリポジトリが静かに壊れる。

そのため各フックは処理の最後に**ローカルのフックへ委譲する**（`_lib.sh` の `chain_local_hook`）。
`git rev-parse --git-common-dir` から実体を引くので `core.hooksPath` の影響を受けず、
自分自身を呼ぶ場合は再帰を避ける。委譲先の終了コードはそのまま伝播する。

### 検証済みの挙動

隔離したリポジトリ（`HOME` ごと差し替え）で実測した。

| # | 操作 | 結果 |
|---|---|---|
| 1 | 通常ファイルのコミット | 通る |
| 2 | `.env` のコミット | **止まる**（コミット数が増えない） |
| 3 | `git commit --no-verify` | 通る |
| 4 | 通常の push | 通る |
| 5 | 保護ブランチへの `push -f` | **止まる**（remote が変化しない） |
| 6 | 保護ブランチの削除 | **止まる**（remote に残る） |
| 7 | `.git/hooks/pre-commit` への委譲 | 実行される |
| 9 | 保護**外**ブランチへの `push -f` | 通る（誤爆しない） |

`install.sh` は既に別の値が入っている `core.hooksPath` を上書きせず exit 1 する。

## permissions 層（deny のみ）

`ask` が機能しない以上、Claude Code 側で本当に効くのは `deny` だけになる。
`permissions/deny-recommended.json` がその雛形で、`permissions/apply.py` で差分マージする。

```bash
permissions/apply.py                    # dry-run。何が増えるか見るだけ
permissions/apply.py --write            # 適用（実体側に .bak を残す）
permissions/apply.py --to path/to/settings.json
```

既存の規則は消さず和集合を取る。冪等なので何度実行してもよい。

### 引数を制約するパターンは書かない

公式ドキュメントが明記しているとおり、Bash の引数を絞る規則は脆い。
`Bash(git push --force *)` は `git push -f` にも `--force-with-lease` にも、
オプション順を変えた形にも当たらない。

そこで**この層はコマンド名単位に絞る**。`sudo` `dd` `mkfs` `fdisk` `shred` `chattr`
`shutdown` など、「そのコマンド自体をエージェントに使わせない」と言い切れるものだけを置く。
引数レベルの判定（強制 push、秘密情報のコミット）は git 層が担当する。**層ごとに
得意な粒度が違う**ので、同じことを両方でやろうとしないこと。

`deny` は問い返しが無い。広げすぎると作業が止まり、結局まるごと外される。
足すときは「自分が普段 Claude に使わせているか」で判断する。

### 書き方の注意

- **ファイル系は `Edit(...)` を使う。** `Write(...)` `NotebookEdit(...)` `MultiEdit(...)` の
  パス規則は受理されるが**参照されない**（起動時に警告が出る）。`Edit(...)` は
  ファイル編集ツール全体に効く
- **絶対パスは `//` から始める。** 単一の `/` は「設定ファイルの位置からの相対」を意味する。
  ホームからは `~/` が使える
- **`~/.claude/settings.json` が symlink なら実体側も併記する。** 雛形は
  `~/dotfiles/.claude/settings.json` も同時に拒否している。片方だけでは迂回できてしまう
- **`deny` は先頭の環境変数代入を跨いで一致する。** `FOO=bar rm -rf tmp/` も `Bash(rm *)` に当たる
- **ラッパーは剥がされない。** `npx` `docker exec` `devbox run` 等は内側のコマンドの規則で
  覆えない。必要ならラッパーごと規則を書く

## 設計上の決定

### fail-safe（判定不能なら ask）

`guardrails` の判定器が動かない・落ちた場合、素通し（fail-open）にはせず確認ダイアログへ倒す。

- **fail-open** はガードレールとして意味を成さない。壊れていることに気付けない。
- **fail-close（deny）** は判定器が壊れた瞬間に全プロジェクトで作業不能になる。
- したがって既定は **ask**。人間が判断すれば進める。

`userConfig.decision` を `deny` にすれば即ブロックへ切り替えられる。

### `ask` は環境によって黙って消える（実測）

**この設計を読む前に知っておくべき事実。** Claude Code v2.1.220 で、PreToolUse フックが返した
`permissionDecision: "ask"` が確認ダイアログとして**表示されない**ことを実測した。
`permissionMode` が `default` でも `acceptEdits` でも同じ。同じフック・同じ経路で
`deny` に差し替えると即座にブロックされ理由文も表示されるため、フック機構・出力形式・
exit code はいずれも正常で、`ask` という決定の扱いだけが飛んでいる。

これは公式ドキュメントの記述と食い違う。[permissions](https://code.claude.com/docs/en/permissions)
の "Extend permissions with hooks" は次のように書いている。

> The hook output can deny the tool call, **force a prompt**, or skip the prompt to let the call proceed.

**フック固有の問題ではない。** `permissions` の `ask` **ルール**（フックを介さない設定側）でも
同じことが起きる。対照実験で確定した。

| 設定 | 投入したルール | 結果 |
|---|---|---|
| `permissions.deny` | `Bash(touch:*)` | **即座にブロック**。設定が読み込まれている証拠（再起動不要） |
| `permissions.ask` | `Bash(rm:*)` | **確認が出ず素通し** |

同じファイルの `deny` が効いている以上、設定が読まれていないという説明は成り立たない。
壊れているのはフック経由の `ask` ではなく **`ask` という経路そのもの**。

**したがってこの環境で確実に止められるのは `deny` と git 層だけ。**
`ask` に依存する仕組みは、動いているように見えて何も守っていない。

**既定を `ask` から動かしてはいない。** `deny` は判定器が壊れた瞬間に全プロジェクトで作業不能に
なり、上の fail-safe 方針を撤回することになるため。代わりに**黙っているのをやめる**方向で解いた
（下記の自己診断）。確実に止めたい環境では `userConfig.decision` を `deny` にすること。

自分の環境で `ask` が表示されるかは一発で確かめられる。

```bash
rm -f /tmp/guardrails-manual-check   # 確認が出なければ、その環境では検出しても素通しになる
```

### 自己診断（SessionStart）

黙って死ぬガードレールは、自分用なら「おかしいな」で済むが、配布すると害になる。
守られていると思わせて守っていないのは、何も無いより悪い。

`scripts/selfcheck.sh` が毎セッション開始時に、登録の有無ではなく **実際に動くか** を確認する。
`guard.sh` を合成ペイロード（実在しないパスを対象にした `rm -rf` と `.env` への書き込み）で
実際に起動し、判定器が決定を返すところまで通しで検査する。異常なら `systemMessage` で
ユーザーに警告し、`additionalContext` で Claude 側にも「ガードレールは効いていないので
不可逆操作の前に自分で確認を取れ」と伝える。診断自体が失敗した場合も黙らず「生死不明」と報告する。

正常時も**実行中のプラグインのパスを毎回報告する**。これは飾りではない。下記の落とし穴で
実際に 2 セッションを溶かしたため、どの `guard.sh` が動いているかは常に見えている必要がある。

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
- [x] 実セッションでフックが発火するか → **発火する。実測済み**
      （`CLAUDE_PLUGIN_ROOT` はリポジトリ側を指す。フック経由の stdout に正しい JSON が出ている）
- [ ] **`ask` が確認ダイアログとして表示されない**（v2.1.220、`default` / `acceptEdits` の両方で実測）。
      `deny` は同一経路で機能するため、フック機構ではなく `ask` の扱いの問題。
      上流へ報告するか、`deny` 前提の運用に寄せるかは未決
- [x] `permissions` の `ask` **ルール**も表示されない。同ファイルの `deny` は効く（対照実験で確定）。
      **`ask` 経路そのものが機能していない。** 確実に止めるには `deny` か git 層を使う
- [x] 多層防御の git 層 → `githooks/` として実装。隔離環境で 7 通り実測済み
- [ ] `githooks/install.sh` をグローバルへ適用するかは未決（現在は harness に `--local` 適用のみ）
- [x] `permissions` 雛形の提供 → `permissions/deny-recommended.json` + `apply.py`
- [ ] 雛形を実環境へ適用するかは未決（`apply.py --write`）
- [ ] OS/FS 層（`chattr +i`）と `trash-cli` による `rm` の置換は手付かず
