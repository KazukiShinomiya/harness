---
description: herdr の隣のペインに、差分 (hunk)・Markdown (leaf)・terraform / terragrunt の plan を表示してユーザーに見せる。「diff を見せて」「隣に出して」「Markdown をプレビューして」「plan を見せて」と頼まれたとき、または変更をユーザーにレビューしてもらう場面で使う。
---

# herdr の隣のペインに表示する

ユーザーに見せたいものを、Claude のペインの隣に開く。端末へ長い出力を流す代わりに使う。

## 前提を確かめる

```bash
test "${HERDR_ENV:-}" = 1
```

失敗したら herdr の中で動いていない。そう伝えて、この skill は使わない（必要なら通常の出力で見せる）。

## ペインを用意する

表示用のペインは **この skill が作ったもの 1 つだけ** を使う。作ったペインの ID は覚えておく。

1. 以前に作った表示用ペインがあれば、まだ存在するか確かめる:
   ```bash
   herdr pane get <pane_id>
   ```
   存在すれば閉じる（中で hunk や leaf が動いていて、そのままでは次のコマンドを受け付けないため）:
   ```bash
   herdr pane close <pane_id>
   ```
2. 右に新しく分割する。ID は必ず返ってきた JSON から読む（jq は無いので python3 を使う）:
   ```bash
   herdr pane split --current --direction right --cwd "$PWD" --no-focus \
     | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["pane"]["pane_id"])'
   ```
   Claude のペインが縦長で狭いときは `--direction down` にする（`herdr pane layout --pane "$HERDR_PANE_ID"` で確認できる）。

## 表示する

`herdr pane run <pane_id> "<command>"` で実行する。パスに空白があれば引用符で囲む。

| 見せるもの | コマンド |
|---|---|
| 作業ツリーの差分 | `hunk diff` |
| ステージ済みの差分 | `hunk diff --staged` |
| 直前（または指定）のコミット | `hunk show [<commit>]` |
| ブランチとの差分 | `hunk diff <base-branch>` |
| 特定のファイルだけ | `hunk diff -- <path>` |
| Markdown | `leaf --width $(tput cols) <file.md>`（書き換えながらなら `--watch` を足す） |
| terraform の plan | `terraform -chdir=<dir> plan` |
| terragrunt の plan | `terragrunt --working-dir <dir> plan`（1.x では `-C` ではない） |

表示したら、何をどのペインに出したかをユーザーに一言で伝える。閉じ方も添える（hunk と leaf は `q`）。

## 内容を Claude が読む必要があるとき

plan の結果などを Claude 自身も確かめるなら:

```bash
herdr pane wait-output <pane_id> --regex "Plan:|No changes|Error" --timeout 300000
herdr pane read <pane_id> --source recent-unwrapped --lines 200
```

## してはいけないこと

- **`herdr pane zoom` を使わない。** Claude のペインが隠れ、ユーザーが Claude を操作できなくなる。
- 表示用ペインで `apply` / `destroy` を実行しない（infra-guard フックでも止まる）。plan まで。
- この skill が作っていないペインを閉じない、コマンドを送らない。
- `--no-focus` を外してユーザーのフォーカスを奪わない。
- `herdr server stop` を実行しない。
