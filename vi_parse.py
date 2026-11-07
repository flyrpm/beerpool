"""Parse a VegasInsider odds page (spread / total / moneyline tables) into rows.

Usage: python3 -I vi_parse.py page.html > lines.json
Each row: {market, rot, team, cells:[{line, price}|null x N], books:[...]}
"""
import html
import json
import re
import sys

BOOKS = ["Open", "bet365", "BetMGM", "DraftKings", "Caesars", "FanDuel",
         "HardRock", "Fanatics", "Kalshi", "Consensus"]


def txt(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def parse_cell(c):
    t = txt(c).replace("›", "").replace("+ ", "").strip()
    t = t.replace("even", "+100").replace("PK", "0")
    m = re.match(r"^([ou]?)\s*([+-]?\d+(?:\.\d)?|0)?\s*([+-]\d{3,4})?", t)
    if not t or not m or (m.group(2) is None and m.group(3) is None):
        return None
    pre, line, price = m.groups()
    out = {}
    if line is not None:
        out["line"] = float(line)
        if pre:
            out["ou"] = pre
    if price:
        out["price"] = int(price)
    return out


def main(path):
    s = open(path, encoding="utf-8", errors="replace").read()
    rows = []
    for market, body in re.findall(
            r'<tbody id="odds-table-(spread|total|moneyline)--\d+"[^>]*>(.*?)</tbody>', s, re.S):
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(tds) < 5:
                continue
            head = txt(tds[0])
            m = re.match(r"^(\d+)\s+(.*)$", head)
            if not m:
                continue
            cells = [parse_cell(c) for c in tds[1:]]
            rows.append({"market": market, "rot": int(m.group(1)),
                         "team": m.group(2).strip(), "cells": cells})
    json.dump({"books": BOOKS, "rows": rows}, sys.stdout, indent=0)


if __name__ == "__main__":
    main(sys.argv[1])
