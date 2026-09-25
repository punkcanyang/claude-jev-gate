#!/bin/sh
# PermissionRequest hook launcher. Interpreter order:
#   $CLAUDE_JEV_GATE_PYTHON > $CLAUDE_JEV_GATE_TYPESAFE_VENV/bin/python
#   > /workspace/tools/typesafe-venv/bin/python (original dev box) > python3
# If no interpreter is found the hook exits non-zero, which Claude Code treats
# as "no decision" and falls back to the normal human prompt.
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PY="${CLAUDE_JEV_GATE_PYTHON:-}"
if [ -z "$PY" ] && [ -n "${CLAUDE_JEV_GATE_TYPESAFE_VENV:-}" ] && [ -x "$CLAUDE_JEV_GATE_TYPESAFE_VENV/bin/python" ]; then
  PY="$CLAUDE_JEV_GATE_TYPESAFE_VENV/bin/python"
fi
if [ -z "$PY" ] && [ -x /workspace/tools/typesafe-venv/bin/python ]; then
  PY=/workspace/tools/typesafe-venv/bin/python
fi
exec "${PY:-python3}" "$DIR/permission_request.py"
