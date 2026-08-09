# SESSION_STATE

最終更新: 2026-08-09

## 現在の状況

多層防御が**四層**になった。`tests/run.sh` は 67 項目すべて成功。
**リポジトリは public**（<https://github.com/KazukiShinomiya/harness>）。master に push 済み。

**`ask` という経路そのものが機能しない**（Claude Code v2.1.220）。PreToolUse フック経由でも
`permissions` の `ask` ルールでも確認が出ず、`deny` は両経路とも効く。対照実験で確定した。
こちらでは直せないため、確実に止めたいものは `deny` と git 層へ寄せてある。

**どの層が実際に効いているかは、ここに書かない。** 起動時の自己診断が四層を毎回実測して
報告するので、それを読むこと。手で書いた表は機械が変われば嘘になる——実際、2026-08-02 版の
表は「permissions 12 件・git 層適用済み・OS/FS 層適用済み」と書いていたが、この機では
三層とも入っていなかった。診断を入れた初日にそれが露見した。

## 前回の戦果

**自己診断をプラグイン層から四層へ広げた。** これまで見ていたのは `guard.sh` の往復だけで、
残る三層は誰も見ていなかった。`permissions` 層が一件も適用されていない状態が何セッションも
気付かれずに続いていたのは、それが理由。

- **未適用と故障を分けた。** 層を入れていない環境の方が多いので、未適用は報告するだけで
  警告しない（毎回鳴らせば読まれなくなる）。`systemMessage` を出すのは
  「導入済みなのに機能していない」場合だけ。拾うのはいずれも**それ自体は何のエラーも
  出さない**もの——`core.hooksPath` が壊れたパスを指す、`pre-commit` から実行権限が落ちる、
  `settings.json` が壊れた JSON、`~/.local/bin/rm` を置いたのに PATH が拾わない、
  `rm-guard` は効いているが `trash-put` が無い
- **この機の実測: 三層とも未適用だった。** `git config --get core.hooksPath` は global も
  local も rc=1、`~/.local/bin/rm` は存在せず、`trash-put` も未導入。
  SESSION_STATE の表は別の機の状態を書いていた
- テストを 56 → 67 項目へ。四層の診断は環境そのものを読むため、`HOME` / `PATH` /
  `GIT_CONFIG_GLOBAL` を隔離した値へ差し替えて走らせる（そうしないとこの機の導入状況で
  結果が変わる）。診断は 0.16 秒、`SessionStart` の timeout は 15 秒

## 次の行動

1. **この機に三層を入れる。** 診断が「未適用」と言い続けている状態。入れるなら
   `githooks/install.sh`、`permissions/apply.py --write`、`osfs/install.sh`
   （`osfs` は先に `sudo apt install trash-cli`）。
   入れないなら「入れない」と決めること——診断が毎回報告するので、放っておくと慣れて読まなくなる。
2. **CI が無い。** public なのに `.github/` が無く、`tests/run.sh` を通すのは人間の記憶だけ。
   「口約束でなく仕組み」という方針とここだけ矛盾している。
3. **判定器の穴（実測）。** `rm -fr` と `rm --recursive --force` は素通りする
   （トークン完全一致のため）。`--build` は単独パターンなので `make --build` で誤爆する。
   `protected_paths` は matcher が `Edit|Write|NotebookEdit` のみで、
   `cat foo > ~/.ssh/config` のような Bash 経由の書き込みを見ていない。
4. `chattr +i` は未適用のまま。代償が重い項目ばかりなので保留してある。
   掛けるなら `osfs/immutable.sh status` を読んでから選ぶこと。
   **`~/.ssh/authorized_keys` を固める案は調査のうえ見送った**——ファイルが存在せず、
   `openssh-server` 自体が未導入（`sshd` も動いていない）。守る対象がまだ無い。
5. `session-harness` は初版のまま手付かず。急ぐ理由は無い。
6. public にしたので、他人が入れられる状態になった。`install.sh` は四層のうち
   プラグイン層しか入れないため、外からなぞると残り三層を落とす（未検証）。

## 決定事項・メモ

- **状態は書かずに測る。** 手で書いた状態表は書いた瞬間から腐り、機械をまたぐと嘘になる。
  「今どうなっているか」は自己診断に言わせ、ここには「なぜそう決めたか」だけ残す。
- **未適用は警告しない。故障だけ警告する。** 未適用で毎セッション鳴らすと、やがて誰も
  読まなくなり、本当の故障も一緒に見落とす。
- **黙らないことと止めることは別。** 危険でないものを止める必要は無いが、黙ってよいわけでもない。
  `session-harness` は失敗も不在も報告するが、止めはしない。
- **OS/FS 層だけ思想が違う。止めずに取り消せるようにする。** `rm` は日常的に使うので確認を
  挟むと長続きしない。消えたものが戻せるなら止める必要がない。
- **ゴミ箱が使えないとき `rm-guard` は本物の `rm` へ落とさず止まる。** 落とすと「守られている
  つもりで守られていない」状態が黙って続く。このリポジトリが潰そうとしている失敗そのもの。
- **スクリプトの後始末は `HARNESS_RM_REAL=1 /usr/bin/rm` で書く。** 素の `rm` だと一時ファイルが
  全部ゴミ箱へ溜まり、本当に戻したいものが埋もれる。`tests/run.sh` の `trap` が最初の被害者に
  なった。捨てると分かっているものまでゴミ箱へ送らないこと。
- **fail-safe の既定は `ask` のまま。** `deny` にすると判定器が壊れた瞬間に作業不能になる。
- **層ごとに得意な粒度が違う。** `permissions.deny` はコマンド名単位、git 層は引数・内容単位、
  プラグインは動的判定、OS/FS 層は呼び出し元を問わない。同じことを複数層でやろうとしない。
- **判定器は `guard.sh` 経由で呼び、exit 2 を返さない**（ブロック扱いになるため）。
- **導入は手順ゼロにできない。** プロジェクトスコープの `extraKnownMarketplaces` は効かない（実測）。
- **`githooks` の保護パターンと `protected_paths.py` は意図的に重複させてある。**
  片方を変えたらもう片方も見ること。`tests/run.sh` が主要パターンの両層存在を確認する。
- **変更したら `tests/run.sh` を通すこと。** 使い捨てのコマンドで確認して終わりにしない。
- **`userConfig` の `multiple: true` はカンマ区切り**（`String(配列)`。生バイトで確認）。
  設定は新セッションでしか読まれず、プロジェクトスコープの `pluginConfigs` は効かない。
- v2.1.220 の validator は `metadata.pluginRoot` による source 短縮形を拒否する。
- **起動は必ず `~/repos/harness` から。** `/mnt/e/work/harness` で起動すると SESSION_STATE が
  読み込まれない（`session-harness` が「どこを探したか」を報告するので気付ける）。
- **Claude Code は `.claude/settings.local.json` をメモリ上の設定で書き戻す。** 実験で入れた
  `pluginConfigs` を消しても、権限追加のタイミングで復活した。実験値は最後に必ず確認して消すこと。
- 上流報告は既存 [#79356](https://github.com/anthropics/claude-code/issues/79356) へコメント済み
  （[投稿](https://github.com/anthropics/claude-code/issues/79356#issuecomment-5157316941)）。
  Linux / Bash / v2.1.220 でも再現することを対照実験ごと足した。
