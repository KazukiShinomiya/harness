# SESSION_STATE

最終更新: 2026-08-09

## 現在の状況

多層防御が**四層**になった。`tests/run.sh` は 85 項目すべて成功し、**push と PR のたびに
GitHub Actions でも走る**（`.github/workflows/tests.yml`）。
**リポジトリは public**（<https://github.com/KazukiShinomiya/harness>）。master に push 済み。

**`ask` という経路そのものが機能しない**（v2.1.220 で確定、**v2.1.226 でも再現**）。PreToolUse
フック経由でも `permissions` の `ask` ルールでも確認が出ず、`deny` は両経路とも効く。
こちらでは直せないため、確実に止めたいものは `deny` と git 層へ寄せてある。

**どの層が実際に効いているかは、ここに書かない。** 起動時の自己診断が四層を毎回実測して
報告するので、それを読むこと。手で書いた表は機械が変われば嘘になる——実際、2026-08-02 版の
表は「permissions 12 件・git 層適用済み・OS/FS 層適用済み」と書いていたが、この機では
三層とも入っていなかった。診断を入れた初日にそれが露見した。

## 前回の戦果

**プラグイン層だけが未適用だった。** 積み残しを洗っていて見つけた。marketplace が未登録で
`enabledPlugins` も無く、`guardrails` も `session-harness` も動いていなかった。残る三層
（permissions / git / OS/FS）は実測で生きていた。

**皮肉なことに、これは自己診断が拾うはずの故障だった。** 診断を載せている層そのものが
抜けていたので、誰も報告しなかった。「状態は書かずに測る」には、測る器械が生きていることの
確認が要る——器械の不在だけは器械が言えない。

- marketplace を**ローカルパス**（`~/repos/harness`）で登録し、両プラグインを導入。
  診断が四層すべて「有効」と答えるようになった
- `userConfig` は 4 項目とも既定値で足りる（`decision=ask`、`state_file=SESSION_STATE.md`）

**dotfiles と役割を整理した。** 正本（`~/repos/dotfiles`）の方が 14 件先行していて、
`~/.claude` はその整備前で止まっていた。単純な同期ではなく双方向のマージになった。

- 正本→この機: `allow` 44 件・`defaultMode: acceptEdits`・SessionStart の `run-hook.sh` 化・
  **インライン PreToolUse の撤去**（guardrails へ移譲済み）・`enabledPlugins`
- この機→正本: deny 7 件（`sudo`/`su`/`doas` と設定ファイル保護）。push 済み（`417dc14`）
- **`~/.claude/hooks/` が存在しなかった。** 正本の SessionStart フックは
  `[ -x "$f" ]` が偽になり丸ごと不発だった（設計どおり黙って落ちる）。`setup.sh` が解消

**`ask` を 2.1.226 で撃ち直した。直っていない。** 存在しないコマンド名を二つ用意し、
片方を `ask`、片方を `deny` へ登録して同じ形で実行した（副作用ゼロで三通りに分かれる——
素通りなら `command not found`、`deny` ならブロック、`ask` なら確認）。
`deny` はブロックされ、`ask` は確認が出ないまま実行された（rc=127）。
同一書式・同一構造での対照なので、書式ミスの疑いは潰れている。
**`deny` が効いたこと自体が「プロジェクトスコープの `permissions` は実行時に読み直される」
ことの証明**でもあり、これで新セッションを待たずに検証できると分かった。

過去の戦果（要点のみ）: 自己診断を四層へ拡張、判定器の穴を三つ（`rm` の綴り一致→意味判定、
`--build` の誤爆、`protected_paths` の Bash 対応）、CI 導入、この機への git / permissions /
OS/FS 三層の適用。`tests/run.sh` は 85 項目、CI でも緑。

順番に意味がある。**`Bash(sudo:*)` を deny する前に `trash-cli` を入れること。**
deny は再起動不要で即座に効くため、先に入れるとエージェント経由の `sudo` が塞がる。

## 次の行動

1. **v2.1.226 の再現を上流 [#79356](https://github.com/anthropics/claude-code/issues/79356) へ報告する。**
   まだ投げていない。2.1.220 の報告に「2.1.226 でも同じ」を足すだけでよい。
   **PreToolUse 経路は 2.1.226 で未検証**（実測したのは `permissions` の ask ルート）。
   プラグイン層が効く次のセッションなら `rm -f /tmp/guardrails-manual-check` で試せる。
   報告前にそちらも撃っておくと、対照が 2.1.220 のときと揃う。
2. **`protected_paths` の Bash 対応は塞ぎ切っていない。** シェルは任意の書き込み方を
   許すので静的には拾えない（`python -c "open('.env','w')"`、`eval`、`exec 3>`）。
   広げるより、本当に失いたくないものを git 層と OS/FS 層へ寄せる方が筋がいい。
   **オプションの無い `rm file` も発火しない**——日常的すぎるのと、戻す役目は
   `rm-guard` が持っているため。変えるなら `find_rm_hit()` の 1 行。
3. `chattr +i` は未適用のまま。代償が重い項目ばかりなので保留してある。
   掛けるなら `osfs/immutable.sh status` を読んでから選ぶこと。
   **`~/.ssh/authorized_keys` を固める案は見送ったままでよい。ただし理由が機ごとに違う。**
   この機では `openssh-server` は導入済み（1:9.6p1）、`ssh` サービスは **active**、
   `authorized_keys` も**存在する**（0 バイト・鍵ゼロ）。「未導入だから守る対象が無い」
   という以前の記述はこの機には当てはまらない。それでも結論は同じ——空のまま固めると
   自分が鍵を足すときに詰まるだけ。鍵を入れたら、そのとき固めればよい。
4. `session-harness` は初版のまま手付かず。急ぐ理由は無い（動いてはいる）。
5. public にしたので、他人が入れられる状態になった。`install.sh` は四層のうち
   プラグイン層しか入れないため、外からなぞると残り三層を落とす。
   **この機ではローカルパス登録で入れたので、`install.sh` の経路は依然として未検証。**

## 決定事項・メモ

- **状態は書かずに測る。** 手で書いた状態表は書いた瞬間から腐り、機械をまたぐと嘘になる。
  「今どうなっているか」は自己診断に言わせ、ここには「なぜそう決めたか」だけ残す。
- **未適用は警告しない。故障だけ警告する。** 未適用で毎セッション鳴らすと、やがて誰も
  読まなくなり、本当の故障も一緒に見落とす。
- **状態表を消しても、決定の根拠に混ざった機械固有の事実は残る。** 「`sshd` が動いていない
  から `authorized_keys` は守らなくていい」のような判断は、機械が変われば前提から崩れる。
  結論だけ移して前提を確かめ直さないと、正しい結論を間違った理由で持ち続けることになる。
  次に判断を書くときは「どの機で測ったか」を添えること。
- **`.github/workflows/` を含む push は HTTPS リモートでは通らない。** OAuth トークンに
  `workflow` スコープが無いため GitHub が弾く。**origin は SSH へ切り替え済み**
  （`git@github.com:KazukiShinomiya/harness.git`）なので、以後は素の `git push origin master`
  で通る。他の機や別クローンで同じことに当たったら、そこも SSH にすること。
- **`!` 経由の `sudo` はパスワードを読めない。** TTY が無いため。この機は passwordless
  sudo ではないので、`sudo` が要るものは実端末で打つしかない。`python3-venv` も不完全で、
  sudo 抜きに pip で入れる逃げ道も無かった。
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
- **permissions は実行時に読み直される。hooks は新セッションでしか読まれない。** 混同しない。
  権限の挙動を試すのに新セッションは要らない（`.claude/settings.local.json` は gitignore 済みで
  実験に使える。ただし Claude Code が書き戻すので実験値は最後に消して `grep -c` で確認する）。
- **権限の実験に複合コマンドを使わない。** `probe --check; echo "rc=$?"` の後半が `allow` に
  マッチしていて、素通りが `ask` の失敗によるものか `allow` の勝ちによるものか切り分けられなく
  なった。`deny` は `allow` に勝つので対照側だけ無傷に見え、危うく誤った結論を出すところだった。
  単独コマンドで撃ち直すこと。終了コードが要るなら別の呼び出しで取る。
- **層ごとに得意な粒度が違う。** `permissions.deny` はコマンド名単位、git 層は引数・内容単位、
  プラグインは動的判定、OS/FS 層は呼び出し元を問わない。同じことを複数層でやろうとしない。
- **判定器は `guard.sh` 経由で呼び、exit 2 を返さない**（ブロック扱いになるため）。
- **導入は手順ゼロにできない。** プロジェクトスコープの `extraKnownMarketplaces` は効かない（実測）。
- **この機の marketplace はローカルパス登録**（`~/repos/harness`。`install.sh` の GitHub 経由ではない）。
  ここは harness 自体の開発機なので、ローカルの修正が push を挟まず即反映される方が都合がよい。
  外から入れる人は `install.sh` をなぞる。`claude plugin marketplace list` は絶対パスで解決を報告する。
- **dotfiles と harness の役割分担。** 正本 `dotfiles/.claude/settings.json` が
  `enabledPlugins` と `extraKnownMarketplaces` を持ち、harness が実体を配る。
  dotfiles の `setup.sh` は**導入まではせず**、未登録なら手順を出して知らせるだけ
  （外部リポジトリの取得は人間の手に残す設計）。`~/.claude/settings.json` は
  正本＋`settings.machine.json` の**シャロー top-level マージ**を `setup.sh` が生成する
  プレーンコピー——正本を編集したらこの機で `setup.sh` を再実行しないと反映されない。
  マージが浅いので `settings.machine.json` に `permissions` を書くと正本の同ブロックが丸ごと消える。
- **層を settings.json からプラグインへ移す瞬間、谷間ができる。** プラグインのフックは
  新セッションでしか読まれないのに、`settings.json` の撤去は即座に効く。移譲した当日の
  セッションは無防備になる。順序を選べるなら、プラグインを入れてから撤去すること。
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
