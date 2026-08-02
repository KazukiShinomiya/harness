# harness

各プロジェクトへハーネスとガードレールを撒くための道具立て。
このリポジトリ自体がマーケットプレイスを兼ねる。

| ディレクトリ / ファイル | 層 | 効く範囲 |
|---|---|---|
| `install.sh` | 導入 | マーケットプレイス登録とプラグイン導入を包んだだけのもの |
| `tests/run.sh` | 回帰テスト | 全層をまとめて確認（29 項目、副作用なし） |
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
| `session-harness` | `SESSION_STATE.md` の読み込みと更新運用 | なし（hook による文脈注入 + skill）。失敗と不在は報告する |

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

## テスト

```bash
tests/run.sh
```

判定器・`guard.sh` の fail-safe・両プラグインの自己診断・`permissions/apply.py`・git 層を
まとめて確かめる（29 項目）。失敗があれば非 0 で終了する。

**副作用は持たない。** git のテストは `HOME` ごと差し替えた隔離リポジトリで行うので、
ユーザーのグローバル設定にも既存のリポジトリにも触れない。実行後に
`core.hooksPath` が空のままであることも確認済み。

テストが無ければ、壊れても黙って壊れる。このリポジトリが一貫して潰そうとしている失敗と
同じものになるので、確認は使い捨てのコマンドで済ませず必ずここへ足すこと。

## 実セッションでの検証手順

```bash
cd ~/repos/harness
claude --plugin-dir ~/repos/harness/plugins/guardrails
```

`/hooks` を開くと `Plugin Hooks` として 3 件が並ぶ。`PreToolUse` が 2 件
（`Bash` と `Edit|Write|NotebookEdit`）、`SessionStart` が 1 件（自己診断）。

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
  これを取り違えて「フックが発火しない」と 2 セッション誤診した。
  なお `path` には `~/repos/harness` のような**チルダ表記が使える**（展開されて解決されることを
  `claude plugin list` で確認済み）。dotfiles で共有するなら絶対パスを避けること
- **診断ログの出力先はセッションを跨いで生存するパスにする。** scratchpad はセッション終了時に
  消える。`>> ... 2>/dev/null || true` と併せると、書き込み失敗が握りつぶされて
  「ログが増えない = フックが動いていない」と誤読する
- 起動時に `userConfig` の入力を求められるかを見ておく。求められるなら `extra_patterns` に
  値を 2 つ入れることで、`multiple: true` の直列化形式（TODO）もそのまま確認できる

## インストール

```bash
./install.sh                # マーケットプレイス登録 + 両プラグイン導入
./install.sh --guardrails   # guardrails だけ
./install.sh --dry-run      # 走らせるコマンドを見るだけ
```

中身は 2 コマンドなので手で打ってもよい。

```bash
claude plugin marketplace add KazukiShinomiya/harness   # 自分用ならローカルパスでも可
claude plugin install guardrails@harness
```

`--scope project` を付けるとリポジトリの `.claude/settings.json` に `enabledPlugins` が書かれ、
clone した全員へ届く。ただしプロジェクトスコープは workspace trust の承認を経てから読み込まれ、
background monitors は読み込まれない。

### 「clone するだけ」にはできない（実測）

`extraKnownMarketplaces` と `enabledPlugins` を対象リポジトリの `.claude/settings.json` に
コミットしておけば導入手順ゼロになる、と考えたが**ならない**。
プロジェクトスコープの `extraKnownMarketplaces` は効かない。

隔離環境で使い捨てのマーケットプレイスを作って確かめた。

| 置いたもの | 結果 |
|---|---|
| プロジェクト設定の `hooks`（プラグイン非経由） | **発火する**（対照。設定ファイル自体は読まれている） |
| プロジェクト設定の `extraKnownMarketplaces` + `enabledPlugins` | プラグインが読み込まれない |
| 同上の状態で `claude plugin marketplace list` | **マーケットプレイスとして認識すらされない** |

直接フックが効く以上「設定が読まれていない」では説明できない。このキーがプロジェクト
スコープでは扱われないということ。したがって marketplace の登録はユーザー自身が行う必要があり、
`install.sh` はその 2 コマンドを包んだだけのもの。

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
| 8 | 保護**外**ブランチへの `push -f` | 通る（誤爆しない） |

さらに `~/repos/harness` 自身へ `--local` で適用した状態でも、`.env` のコミットが
止まることを実リポジトリで確認済み。

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

雛形は 18 件だが、**全部入れる必要はない**。作者の環境ではディスク破壊系 8 件と電源系 4 件の
計 12 件だけを適用している。`sudo` は `apt install` 等を任せられなくなるため、
`Edit(~/.claude/settings.json)` 系は設定作業が全て手動になるため外した。
`--from` に部分集合の JSON を渡せば群単位で入れられる。

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

上流への報告の下書きが [`docs/upstream-report-draft.md`](docs/upstream-report-draft.md) にある
（再現手順 2 通りと `deny` の対照つき）。提出するかは未定。

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

正常時も**実行中のプラグインのパスを毎回報告する**。これは飾りではない。上記の落とし穴で
実際に 2 セッションを溶かしたため、どの `guard.sh` が動いているかは常に見えている必要がある。

実体は `plugins/guardrails/scripts/selfcheck.sh`。異常系（`CLAUDE_PLUGIN_ROOT` 未設定、
判定器が黙る）を壊した複製で実測したうえ、実際の `SessionStart` で発火することも
`~/repos/harness` から新規セッションを起こして確認済み。

### 「黙らない」は session-harness にも適用する

`session-harness` は当初、注入の失敗を例外ごと握り潰していた。危険ではない（偽の安心を
作らない）というのがその理由だったが、**それでも黙ってよい理由にはならない**。
実際に別ディレクトリから起動したセッションが前回の経緯を知らないまま始まり、
セッションログを漁って復元する羽目になった。

現在は六通りを区別して報告する。

| 状況 | 報告 |
|---|---|
| 読み込めた | どのパスから読んだかを添えて注入 |
| ファイルが無い | **どこを探したか**を伝える。起動位置の取り違えに気付ける唯一の手がかり |
| 空だった | その旨 |
| 読めなかった | `systemMessage` でユーザーにも警告 |
| python が無い | 同上。注入は決して働かない |
| `CLAUDE_PLUGIN_ROOT` 未設定 | 同上 |

止めも確認もしない点は変わらない。**黙らないことと止めることは別**で、
危険でないものを止める必要は無いが、黙ってよいわけでもない。

### プラグインの settings.json では permissions を配れない

Claude Code のプラグインが `settings.json` で供給できるのは `agent` と `subagentStatusLine` の 2 キーのみ。
`permissions.deny` は**プラグインからは**配布できない。

当初はこれを理由に強制力をすべて hooks へ寄せていたが、`ask` が機能しないと分かった時点で
方針を改めた。`permissions` は dotfiles 経由なら配れる（`~/.claude/settings.json` が symlink であるため）
ので、配布経路としては解決済み。現在は `permissions/` と `githooks/` に分けて持たせている。

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

## 既存のグローバル設定からの移行（完了）

`~/.claude/settings.json` に残っていた移植元は削除済み。dotfiles の drift / freshness
チェックだけが残っている（harness とは無関係なので残す）。

移行が済んだかどうかは**確認の有無では判断できない**。本来なら二重に発火して確認が
二度出るはずだが、`ask` が表示されない環境では二重にも見えないため。
設定を直接読んで確かめること。

| グローバル側 | 引き継ぎ先 | 削除してよいか |
|---|---|---|
| `PreToolUse`（`Bash` matcher） | `guardrails` の `irreversible_ops.py` | **可**。トークン境界で判定するぶん精度も高い |
| `SessionStart`（SESSION_STATE 注入） | `session-harness` の `session_state.py` | **順序に注意**（下記） |
| `SessionStart`（dotfiles drift / freshness） | なし | 残す。harness とは無関係 |

### 順序を間違えると SESSION_STATE が黙って読まれなくなる

同じ移行を他の環境でやる人向けに残しておく。**SESSION_STATE の注入を担っているのが
グローバルフックただ一つの状態で先にそれを消すと、引き継ぎ先が無いまま注入が落ちる。**
しかも落ちても何も表示されない。次のセッションが「前回の経緯を知らないまま」始まるだけで、
消してから気付く手段が無い。必ずこの順で行う。

```bash
claude plugin install session-harness@harness   # 先に引き継ぎ先を立てる
# 新規セッションを起こし、SESSION_STATE が文脈に入ることを確認してから
# dotfiles 側でグローバルの SessionStart（注入分）を削除する
```

作者の環境ではこの順で実施し、削除後も新規セッションで
`session-harness: <path> を読み込んだ` と `guardrails: 有効（...）` の両方が出ること、
SESSION_STATE が重複注入されていないことを確認した。

`session_state.py` はグローバル側と等価以上（`userConfig.state_file` でファイル名を変えられ、
空ファイルも弾き、失敗時は黙らず報告する）。

なお `~/.claude/settings.json` の正本は `~/dotfiles/.claude/settings.json` 側にあるため、
削除は dotfiles 側で行い同期する。

## 開発環境上の注意（WSL2）

**`/mnt/e` などの Windows マウント配下で作業しない。** drvfs は inotify を通さないため、
設定ファイルの手編集が Claude Code の file watcher に検知されない。`.claude/settings.local.json` に
hooks を書き足しても `/hooks` に現れず、さらに Claude Code 自身が同ファイルへ書き込んだ時点で
手編集が消える。実測で確認済み。開発は WSL ネイティブ側（`~/repos`）で行うこと。

## TODO

### 決着済み

- [x] 実セッションでフックが発火するか → **発火する。**`CLAUDE_PLUGIN_ROOT` はリポジトリ側を指し、
      フック経由の stdout に正しい JSON が出ている
- [x] **`ask` 経路そのものが機能していない。** フック経由でも `permissions` の `ask` ルールでも
      確認が出ず、`deny` は両経路とも効く（対照実験で確定、v2.1.220、`permissionMode` 非依存）。
      確実に止めるには `deny` か git 層を使う
- [x] 多層防御の git 層 → `githooks/`。隔離環境で 8 通り＋実リポジトリで実測
- [x] `permissions` 雛形 → `permissions/deny-recommended.json` + `apply.py`
- [x] 自己診断 → `SessionStart` で実際に発火するところまで確認

### 未決・未着手

- [x] **グローバル設定からの移行が完了。** `session-harness` を先に入れて注入を確認してから、
      移植元の `PreToolUse`（Bash）と `SessionStart`（SESSION_STATE 注入分）を削除した
- [x] `session-harness` も黙らなくなった。読み込めた / 無い / 空 / 読めない / python 不在 /
      `CLAUDE_PLUGIN_ROOT` 未設定 の 6 通りを区別して報告する（全経路を実測）
- [x] **導入を手順ゼロにはできない。** プロジェクトスコープの `extraKnownMarketplaces` は
      効かない（対照実験で確定）。`install.sh` で 2 コマンドに包む形に落とした
- [ ] `githooks/install.sh` をグローバルへ適用するか（現在は harness に `--local` のみ）
- [ ] `userConfig` の `multiple: true` が hook 環境変数へどう直列化されるか未検証
      （`_common.option_list()` は JSON 配列・改行区切り・カンマ区切りの三通りを受けるようにしてある）
- [ ] OS/FS 層（`chattr +i`）と `trash-cli` による `rm` の置換
- [ ] `ask` の件の上流報告。下書きは [`docs/upstream-report-draft.md`](docs/upstream-report-draft.md)。提出は未定
- [ ] `session-harness` は初版のまま手付かず

## License

MIT。[LICENSE](LICENSE) を参照。
