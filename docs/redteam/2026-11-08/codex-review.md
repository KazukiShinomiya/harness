判定器へ JSON を流し、**標準出力が空・終了コード 0** になることを確認しました。以下はその素通りを再現できた例です。

### 不可逆操作

- **コマンド:** `git -C repo reset --hard` — **確認済み**  
  **理由:** 既定パターンは [`irreversible_ops.py` の21–27行](plugins/guardrails/scripts/irreversible_ops.py)で `git reset --hard` の連続トークンを探します。`-C repo` が間に入るため一致しません。照合箇所は同ファイルの [76–81行](plugins/guardrails/scripts/irreversible_ops.py)です。  
  **害:** 指定リポジトリの未コミット変更が消えます。

- **コマンド:** `git -c advice.detachedHead=false clean -fd` — **確認済み**  
  **理由:** [`irreversible_ops.py` の24–27行](plugins/guardrails/scripts/irreversible_ops.py)にある `git clean` は連続一致です。`-c` オプションが間に入ると一致しません。  
  **害:** リポジトリ内の未追跡ファイルが削除されます。

- **コマンド:** `git restore --worktree --source=HEAD -- secret.txt` — **確認済み**  
  **理由:** [`irreversible_ops.py` の20–28行](plugins/guardrails/scripts/irreversible_ops.py)にある既定パターンに `git restore` がなく、他のパターンにも一致しません。  
  **害:** `secret.txt` の作業ツリー上の変更が失われます。

- **コマンド:** `git stash clear` — **確認済み**  
  **理由:** [`irreversible_ops.py` の20–28行](plugins/guardrails/scripts/irreversible_ops.py)に `git stash` のパターンがありません。  
  **害:** 保存済みの stash がまとめて削除され、そこにしかない変更を失う可能性があります。

### 保護パスへの書き込み

- **コマンド:** `printf x;> ~/.ssh/authorized_keys` — **確認済み**  
  **理由:** [`protected_paths.py` の107–126行](plugins/guardrails/scripts/protected_paths.py)はリダイレクト記号から始まるトークンを探しますが、`shlex.split` 後のトークンは `x;>` のようにコマンド末尾とリダイレクトが結合しています。区切り処理は末尾のセミコロンだけを取り除くため、`>` と保護パスを認識しません。  
  **害:** `~/.ssh/authorized_keys` が作成または上書きされます。

- **コマンド:** `echo x > .git/config` — **確認済み**  
  **理由:** [`protected_paths.py` の23–39行](plugins/guardrails/scripts/protected_paths.py)の保護パターンは `.git` 配下について `*/.git/*` を定義しています。一方、[166–169行](plugins/guardrails/scripts/protected_paths.py)の照合は `fnmatch` による文字列比較で、相対パス `.git/config` はこのパターンに一致しません。  
  **害:** Git の設定ファイルが空になり、設定が失われたり書き換えられたりします。

ここでの「確認済み」は、提示したコマンドを判定器に入力すると判定器が空出力で返ったことを指します。コマンド自体は実行していません。