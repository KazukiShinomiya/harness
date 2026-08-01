#!/bin/sh
# SessionStart で状態ファイルを注入する。
#
# ガードレールと違い、注入の失敗は危険ではなく単に文脈が減るだけなので、
# ここは黙って諦める（fail-open）。確認ダイアログに倒す理由がない。
set -u

py=$(command -v python3 || command -v python) || exit 0
exec "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/session_state.py"
