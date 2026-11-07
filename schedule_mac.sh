#!/usr/bin/env bash
# Install / remove the odds snapshot schedule on this Mac (launchd).
#   ./schedule_mac.sh install     # schedule + take one snapshot now as a test
#   ./schedule_mac.sh status      # is it loaded? last log lines, snapshot count
#   ./schedule_mac.sh uninstall
#
# Runs `snapshots.py take` at (Mac local time, assumed Eastern):
#   Thu 18:05 (sheet day) · Fri 21:05 · Sat 09:05 · Sat 11:35 (before noon lock) · Sun 12:35 (NFL)
# launchd runs a missed slot when the Mac wakes, so a sleeping laptop catches up.
# Fallback only: the cloud scheduled task normally takes these and commits them.
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"
LABEL="com.beerpool.snapshot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY="$(command -v python3)"
mkdir -p "$DIR/data"

slot() {  # weekday(0=Sun) hour minute
  printf '    <dict><key>Weekday</key><integer>%s</integer><key>Hour</key><integer>%s</integer><key>Minute</key><integer>%s</integer></dict>\n' "$1" "$2" "$3"
}

case "${1:-}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents"
    {
      cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string><string>$DIR/snapshots.py</string><string>take</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StandardOutPath</key><string>$DIR/data/snapshot.log</string>
  <key>StandardErrorPath</key><string>$DIR/data/snapshot.log</string>
  <key>StartCalendarInterval</key><array>
EOF
      slot 4 18 5; slot 5 21 5; slot 6 9 5; slot 6 11 35; slot 0 12 35
      echo '  </array>'
      echo '</dict></plist>'
    } > "$PLIST"
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"
    echo "Installed $PLIST (python: $PY)"
    echo "Test snapshot now:"
    "$PY" "$DIR/snapshots.py" take
    ;;
  status)
    launchctl list | grep "$LABEL" || echo "not loaded"
    echo "snapshots: $(find "$DIR/data/snapshots" -name '*.json.gz' 2>/dev/null | wc -l | tr -d ' ')"
    tail -5 "$DIR/data/snapshot.log" 2>/dev/null || true
    ;;
  uninstall)
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed $LABEL"
    ;;
  *) echo "usage: $0 install|status|uninstall" >&2; exit 1 ;;
esac
