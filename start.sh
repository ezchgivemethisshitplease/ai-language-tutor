#!/bin/sh
# Local runtime only; works from any current directory on macOS/Linux.
set -eu
TUTOR_LAUNCH_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TUTOR_LAUNCH_PYTHON=${TUTOR_PYTHON:-python3}
if ! command -v "$TUTOR_LAUNCH_PYTHON" >/dev/null 2>&1; then
    printf '%s\n' 'Нужен Python 3.10+. Установи python3 или задай TUTOR_PYTHON путём к Python.' >&2
    exit 1
fi
exec "$TUTOR_LAUNCH_PYTHON" "$TUTOR_LAUNCH_ROOT/tools/web_start.py" "$@"
