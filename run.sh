#!/usr/bin/env bash
# Weekly beer pool sweep.
# Usage: ./run.sh board.pdf "13-63,65-78"   (open game ranges)
# Output: sweep.json (every game priced at the sheet number) + ranked list on stdout.
set -euo pipefail
cd "$(dirname "$0")"
PDF="$1"; OPEN="${2:-1-99}"
pdftotext -layout "$PDF" board.txt
for k in nfl college-football; do
  curl -sS --compressed -m 30 "https://www.vegasinsider.com/$k/odds/las-vegas/" -o "vi_$k.html"
  python3 -I vi_parse.py "vi_$k.html" > "vi_$k.json"
done
python3 -I analyze.py board.txt vi_nfl.json vi_college-football.json --open "$OPEN" > sweep.json
python3 -I - <<'EOF'
import json
c = []
for g in json.load(open("sweep.json")):
    if "mkt_home" not in g:
        print("UNMATCHED", g["num"], g["away"], "@", g["home"]); continue
    H, A = g["home"], g["away"]
    c += [(g["p_home_sheet"], g["num"], f"{H} {g['sheet_home']:+}", g["mkt_home"]),
          (g["p_away_sheet"], g["num"], f"{A} {-g['sheet_home']:+}", -g["mkt_home"])]
    if "p_over_sheet" in g:
        c += [(g["p_over_sheet"], g["num"], f"{A}/{H} OVER {g['total']}", g["mkt_total"]),
              (g["p_under_sheet"], g["num"], f"{A}/{H} UNDER {g['total']}", g["mkt_total"])]
print("cover%  #   pick (at sheet number, push=loss)            market")
for p, n, s, m in sorted(c, reverse=True)[:25]:
    print(f"{p:.3f}  {n:>3}  {s:<45} {m}")
EOF
