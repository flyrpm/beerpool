#!/usr/bin/env bash
# Weekly beer pool card.
# Usage: ./run.sh [board.pdf] [notes.json]
#   board.pdf  default: newest BP*.pdf in ~/Downloads
#   notes.json default: newest notes/*.json (football layer for the week)
# Extra flags go to beerpool.py, e.g.  NOW=2026-11-07T09:00 ./run.sh
set -euo pipefail
PDF="${1:-}"; NOTES="${2:-}"
if [ -z "$PDF" ]; then
  PDF="$(ls -t "$HOME"/Downloads/BP*.pdf 2>/dev/null | head -1 || true)"
  [ -n "$PDF" ] || { echo "usage: ./run.sh path/to/board.pdf [notes.json]" >&2
                     echo "(no BP*.pdf found in ~/Downloads)" >&2; exit 1; }
  echo "Using board: $PDF" >&2
fi
[ -f "$PDF" ] || { echo "not found: $PDF" >&2; exit 1; }
PDF="$(cd "$(dirname "$PDF")" && pwd)/$(basename "$PDF")"
[ -z "$NOTES" ] || NOTES="$(cd "$(dirname "$NOTES")" && pwd)/$(basename "$NOTES")"
cd "$(dirname "$0")"
if [ -z "$NOTES" ]; then
  NOTES="$(ls notes/*.json 2>/dev/null | sort | tail -1 || true)"
  [ -z "$NOTES" ] || echo "Using notes: $NOTES" >&2
fi
python3 build_board.py --pdf "$PDF" ${NOTES:+--notes "$NOTES"} > board.json
python3 beerpool.py board.json --pdf "$PDF" --save-run runs ${NOW:+--now "$NOW"}
