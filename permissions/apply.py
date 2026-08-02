#!/usr/bin/env python3
"""deny 規則を settings.json へ差分マージする。

    apply.py [--to <settings.json>] [--from <rules.json>] [--write]

既定は dry-run。何が増えるかを表示するだけで書き換えない。--write を付けたときだけ
適用し、直前に .bak を残す。既存の規則は消さない（和集合を取る）。

プラグインからは permissions を配れないため、この層だけは手で入れるか
dotfiles 経由で配る必要がある。README の該当節を参照。
"""

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RULES = os.path.join(HERE, "deny-recommended.json")
DEFAULT_TARGET = os.path.expanduser("~/.claude/settings.json")


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", default=DEFAULT_TARGET, help="適用先の settings.json")
    parser.add_argument("--from", dest="source", default=DEFAULT_RULES, help="規則ファイル")
    parser.add_argument("--write", action="store_true", help="実際に書き換える")
    args = parser.parse_args()

    rules = load(args.source).get("permissions", {}).get("deny", [])
    if not rules:
        print("規則ファイルに deny が無い: %s" % args.source, file=sys.stderr)
        return 1

    if not os.path.exists(args.to):
        print("適用先が無い: %s" % args.to, file=sys.stderr)
        return 1

    target = load(args.to)
    current = target.setdefault("permissions", {}).setdefault("deny", [])

    added = [rule for rule in rules if rule not in current]
    if not added:
        print("追加するものは無い（%d 件すべて適用済み）" % len(rules))
        return 0

    print("適用先: %s" % args.to)
    print("追加される deny 規則 %d 件:" % len(added))
    for rule in added:
        print("  + %s" % rule)

    if not args.write:
        print("\ndry-run。実際に適用するには --write を付ける。")
        return 0

    # シンボリックリンクの場合、実体側を退避する。
    real = os.path.realpath(args.to)
    shutil.copy2(real, real + ".bak")

    current.extend(added)
    with open(real, "w", encoding="utf-8") as handle:
        json.dump(target, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print("\n適用した。退避: %s.bak" % real)
    print("元に戻す: mv %s.bak %s" % (real, real))
    return 0


if __name__ == "__main__":
    sys.exit(main())
