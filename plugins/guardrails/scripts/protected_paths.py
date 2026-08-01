#!/usr/bin/env python3
"""書き込み先が保護対象のパスかを判定する。

秘密情報や、壊れると復旧が面倒なものを既定で拾う。プロジェクト固有の保護対象は
userConfig の protected_paths から足せる。
"""

import fnmatch
import json
import os
import sys

import _common

DEFAULT_PROTECTED = (
    # 秘密情報
    ".env",
    ".env.*",
    "*/.env",
    "*/.env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*/id_rsa*",
    "*/id_ed25519*",
    "*credentials*",
    "*/.ssh/*",
    "*/.aws/*",
    "*/.gnupg/*",
    # 壊すと面倒なもの
    "*/.git/*",
    "*/dotfiles/*",
)

REASON = "protected path ({pattern}): {path} -- confirm this write is intended"


def matches(path, pattern):
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(os.path.basename(path), pattern)


def main():
    payload = json.load(sys.stdin)
    tool_input = payload.get("tool_input", {})
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not path:
        return

    resolved = os.path.expanduser(path)
    patterns = list(DEFAULT_PROTECTED) + _common.option_list("protected_paths")
    for pattern in patterns:
        if matches(resolved, pattern):
            _common.emit(REASON.format(pattern=pattern, path=path))
            return


if __name__ == "__main__":
    main()
