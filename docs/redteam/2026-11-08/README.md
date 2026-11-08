# guardrails の穴探し（2026-11-08、Claude による基準）

`plugins/guardrails/scripts/` の判定器に、検体のコマンドを Bash の tool_input として流した。対照の 4 件は検出され（HIT）、**候補の 22 件はすべて素通りした（PASS）**。結果は `result.txt` にある。

```
python3 -I docs/redteam/2026-11-08/run.py docs/redteam/2026-11-08/cases.jsonl
```

検体を Bash の引数に直接書くと、実行する側の guardrails がそれを拾ってしまう。そのため、検体はファイルに置いてある。

## 見立て

- **最も重いもの**: I2 `git -c core.hooksPath=/dev/null commit`。プラグインの層を抜けるうえに、同じコマンドで git 層も外せる
- irreversible_ops の根は一つだ。「語が隣り合っていれば拾う」照合をコマンド全体に当てている。そのため、git のグローバルオプション（I1・I2）、引数の順（I3・I4）、空白の無い区切り（I8〜I10）、`bash -c`（I11。protected_paths にある再帰が、こちらには無い）で抜ける
- protected_paths: 相対パスが `*/` で始まる glob に一致しない（P1・P2）。空白の無いリダイレクト（P3）。書き込み先がディレクトリ名で終わる（P4）。`-c` のまとめ書き（P5）
- ほかの層: `rm` は rm-guard を通るので戻せる（I7 は実害が小さい）。git 層が止めるのは、保護ブランチへの強制 push と削除だけだ。permissions の deny に git・rm の項目は無い

## 直し方の案（未着手）

パターンを足していくのはやめる。共通の部品を一つ作る。

1. 区切りでコマンドを切り分ける（`shlex.shlex(punctuation_chars=True)`）
2. git はグローバルオプション（`-C`・`-c`・`--git-dir` など）を飛ばし、サブコマンドとその引数で判定する
3. パスは payload の `cwd` を使って絶対パスにしてから照合する
4. `-c` の再帰を irreversible 側にも入れる。`-lc` などのまとめ書きも拾う

修正は、Codex との比較（下記）が済むまで保留する案になっている。決めるのはユーザーだ。

## Codex との比較（未実施）

`prompt-for-codex.md` は、Codex に渡す問いだ。除外したのは SESSION_STATE にある既知の穴だけで、この 22 件は伏せてある。Codex がこの外を何件見つけるかで、Codex の価値を測る。OpenAI とはまだ契約していない。
