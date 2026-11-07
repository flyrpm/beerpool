"""Beer pool analyzer: sheet (frozen) vs live market, priced at the sheet number.

Usage: python3 -I analyze.py board.txt vi_nfl.json vi_cfb.json [--open 13-63,65-78]

- Parses the commissioner's board (pdftotext -layout output).
- Matches each game to VegasInsider rows by team name.
- Market line = median of the 7 sportsbooks (bet365, MGM, DK, Caesars, FD, HardRock,
  Fanatics); Kalshi excluded (leans dog). De-vigs the median juice.
- Prices both sides of every spread and total AT THE SHEET NUMBER, with push = loss,
  using a discrete margin distribution with key-number mass (NFL 3/7/10/6/4/1/2,
  CFB 3/7/10/14/17), centred so that it reproduces the market's de-vigged price.
"""
import json
import math
import re
import statistics
import sys

BOOK_IDX = [1, 2, 3, 4, 5, 6, 7]  # cells index: 0=Open, 8=Kalshi, 9=Consensus

# --------------------------------------------------------------- board parsing
ROW = re.compile(
    r"^\s*(\d{1,3})\s+\w{3}, (\w{3} \d+), \d{4}\s+([\d:]+ [AP]M)\s+(.+?)\s{2,}(at|vs)\s{2,}(.+?)\s{2,}(.+?)\s{2,}(\S+)\s+(PK|[+-]?\d+(?:\.\d)?)\s+(\d+(?:\.\d)?)\s*$")


def parse_board(path):
    games = []
    league = "CFB"
    for ln in open(path, encoding="utf-8"):
        if "NFL -" in ln:
            league = "NFL"
        m = ROW.match(ln)
        if not m:
            continue
        num, date, time, away, _, home, tv, fav, line, total = m.groups()
        games.append(dict(num=int(num), date=date, time=time, away=away.strip(),
                          home=home.strip(), fav_abbr=fav, line=float(line if line != "PK" else 0),
                          total=float(total), league=league))
    return games


# --------------------------------------------------------------- name matching
ALIAS = {
    "miami (oh)": "miami oh", "miami": "miami fl", "massachusetts": "umass", "san josé state": "san jose state",
    "hawai'i": "hawaii", "ul monroe": "louisiana-monroe", "florida international": "fiu",
    "unlv": "unlv", "utsa": "utsa", "smu": "smu", "uab": "uab", "ucf": "ucf", "byu": "byu",
    "tcu": "tcu", "lsu": "lsu", "utep": "utep", "uconn": "uconn", "app state": "appalachian state",
    "ole miss": "ole miss", "nc state": "nc state", "jacksonville state": "jacksonville state",
}


def norm(s):
    s = s.lower().replace("&", "and").replace("é", "e").replace("’", "'")
    s = ALIAS.get(s, s)
    return re.sub(r"[^a-z0-9 ]", "", s).strip()


def name_score(board_name, vi_name, league):
    b, v = norm(board_name), norm(vi_name)
    if league == "NFL":
        return 1.0 if v and v.split()[-1] in b.split() else 0.0
    if b == v:
        return 1.0
    bt, vt = b.split(), v.split()
    # "Ohio" must not match "Ohio State"; "Miami" must not match "Miami Ohio".
    if set(bt) == set(vt):
        return 1.0
    abbrev = {"st": "state", "n": "north", "s": "south", "w": "west", "e": "east", "ga": "georgia",
              "fla": "florida", "intl": "international", "tenn": "tennessee", "mich": "michigan",
              "ky": "kentucky", "la": "louisiana", "so": "southern", "c": "central", "car": "carolina"}
    vt2 = [abbrev.get(t, t) for t in vt]
    if vt2 == bt:
        return 0.95
    return 0.0


def pair_rows(vi):
    """Group VI rows into games: (market) -> list of (away_row, home_row)."""
    out = {"spread": [], "total": [], "moneyline": []}
    rows = vi["rows"]
    for i in range(0, len(rows) - 1):
        a, h = rows[i], rows[i + 1]
        if a["market"] == h["market"] and a["rot"] % 2 == 1 and h["rot"] == a["rot"] + 1:
            out[a["market"]].append((a, h))
    return out


def find(pairs, g):
    best, bs = None, 0
    for a, h in pairs:
        s = name_score(g["away"], a["team"], g["league"]) + name_score(g["home"], h["team"], g["league"])
        if s > bs:
            best, bs = (a, h), s
    return best if bs >= 1.9 else None


# --------------------------------------------------------------- pricing model
def american_to_p(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


KEYS = {"NFL": {3: 2.6, 7: 1.9, 10: 1.35, 6: 1.3, 4: 1.25, 1: 1.2, 2: 1.0, 14: 1.3, 17: 1.15},
        "CFB": {3: 1.8, 7: 1.6, 10: 1.3, 14: 1.35, 17: 1.2, 21: 1.15, 4: 1.1, 24: 1.05, 28: 1.1}}
SD = {"NFL": 13.5, "CFB": 16.5}


def margin_dist(mu, league):
    """P(home_margin == k) for k in -80..80 (no ties in football to speak of)."""
    sd = SD[league]
    ks = range(-80, 81)
    w = {}
    for k in ks:
        if k == 0:
            continue
        base = math.exp(-0.5 * ((k - mu) / sd) ** 2)
        w[k] = base * KEYS[league].get(abs(k), 1.0)
    z = sum(w.values())
    return {k: v / z for k, v in w.items()}


def p_cover_home(dist, home_line):
    """Home covers home_line (e.g. -3.5) iff margin + line > 0. Push = loss."""
    return sum(p for k, p in dist.items() if k + home_line > 0)


def fit_mu(home_line, p_home, league):
    lo, hi = -60.0, 60.0
    for _ in range(60):
        mid = (lo + hi) / 2
        d = margin_dist(mid, league)
        win = p_cover_home(d, home_line)
        lose = sum(p for k, p in d.items() if k + home_line < 0)
        if win / (win + lose) < p_home:  # de-vigged price excludes pushes
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def total_p_over(mu_tot, line, league):
    sd = 13.0 if league == "NFL" else 15.5
    # integer totals; push = loss
    def cdf(x):
        return 0.5 * (1 + math.erf((x - mu_tot) / (sd * math.sqrt(2))))
    return 1 - cdf(math.floor(line) + 0.5)


def fit_total(line, p_over, league):
    lo, hi = line - 30, line + 30
    for _ in range(60):
        mid = (lo + hi) / 2
        if total_p_over(mid, line, league) < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def consensus(a, h, key="line"):
    al = [a["cells"][i].get(key) if i < len(a["cells"]) and a["cells"][i] else None for i in BOOK_IDX]
    hl = [h["cells"][i].get(key) if i < len(h["cells"]) and h["cells"][i] else None for i in BOOK_IDX]
    ap = [a["cells"][i].get("price") if i < len(a["cells"]) and a["cells"][i] else None for i in BOOK_IDX]
    hp = [h["cells"][i].get("price") if i < len(h["cells"]) and h["cells"][i] else None for i in BOOK_IDX]
    return al, hl, ap, hp


def analyze(games, vis, open_set):
    out = []
    for g in games:
        if open_set and g["num"] not in open_set:
            continue
        vi = vis[g["league"]]
        sp, tt = find(vi["spread"], g), find(vi["total"], g)
        rec = dict(g)
        # sheet home line: favourite abbreviation decides sign
        home_fav = None
        if sp:
            a, h = sp
            al, hl, ap, hp = consensus(a, h)
            hl_valid = [x for x in hl if x is not None]
            if not hl_valid:
                out.append(rec)
                continue
            mh = med(hl)
            # which book prices sit at the median line
            pairs = [(hl[i], hp[i], ap[i]) for i in range(len(hl)) if hl[i] == mh and hp[i] and ap[i]]
            if not pairs:  # median is between two lines (x.25 / x.75): use nearest
                nearest = min(hl_valid, key=lambda x: abs(x - mh))
                pairs = [(hl[i], hp[i], ap[i]) for i in range(len(hl)) if hl[i] == nearest and hp[i] and ap[i]]
                mh = nearest
            ph = statistics.mean(american_to_p(p[1]) for p in pairs)
            pa = statistics.mean(american_to_p(p[2]) for p in pairs)
            p_home_mkt = ph / (ph + pa)
            mu = fit_mu(mh, p_home_mkt, g["league"])
            dist = margin_dist(mu, g["league"])
            # sheet line from home perspective. Infer which side is fav by comparing to market.
            # The board's fav_abbr names the favourite; decide home/away by market sign if ambiguous.
            sheet = g["line"]  # negative number for fav
            # guess favourite side: if market home line < 0 home is market fav.
            fav_is_home = guess_fav_home(g, mh)
            home_fav = fav_is_home
            sheet_home = sheet if fav_is_home else -sheet
            rec.update(mkt_home=mh, mkt_range=[min(hl_valid), max(hl_valid)], books=len(hl_valid),
                       p_home_mkt=round(p_home_mkt, 3), mu=round(mu, 2), sheet_home=sheet_home,
                       p_home_sheet=round(p_cover_home(dist, sheet_home), 3),
                       p_away_sheet=round(p_cover_home({-k: v for k, v in dist.items()}, -sheet_home), 3),
                       kalshi=h["cells"][8].get("line") if len(h["cells"]) > 8 and h["cells"][8] else None,
                       open_home=h["cells"][0].get("line") if h["cells"][0] else None)
        if tt:
            a, h = tt
            ol = [a["cells"][i].get("line") if a["cells"][i] else None for i in BOOK_IDX]
            op = [a["cells"][i].get("price") if a["cells"][i] else None for i in BOOK_IDX]
            up = [h["cells"][i].get("price") if h["cells"][i] else None for i in BOOK_IDX]
            ov = [x for x in ol if x is not None]
            if ov:
                mt = med(ol)
                idx = [i for i in range(len(ol)) if ol[i] == mt and op[i] and up[i]]
                if not idx:
                    mt = min(ov, key=lambda x: abs(x - mt))
                    idx = [i for i in range(len(ol)) if ol[i] == mt and op[i] and up[i]]
                po = statistics.mean(american_to_p(op[i]) for i in idx)
                pu = statistics.mean(american_to_p(up[i]) for i in idx)
                p_over = po / (po + pu)
                mut = fit_total(mt, p_over, g["league"])
                rec.update(mkt_total=mt, total_range=[min(ov), max(ov)],
                           p_over_sheet=round(total_p_over(mut, g["total"], g["league"]), 3),
                           p_under_sheet=round(1 - total_p_over(mut, g["total"], g["league"])
                                               - push_mass(mut, g["total"], g["league"]), 3),
                           open_total=a["cells"][0].get("line") if a["cells"][0] else None)
        out.append(rec)
    return out


def push_mass(mu, line, league):
    if line != int(line):
        return 0.0
    sd = 13.0 if league == "NFL" else 15.5
    c = lambda x: 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))
    return c(line + 0.5) - c(line - 0.5)


ABBR_HOME_HINTS = {}


def guess_fav_home(g, mkt_home):
    """Board names the favourite by abbreviation. Decide if it's the home team."""
    ab = g["fav_abbr"].upper().replace("-", "").replace("&", "")
    home, away = norm(g["home"]).upper().replace(" ", ""), norm(g["away"]).upper().replace(" ", "")

    def hit(name):
        initials = "".join(w[0] for w in norm(name).split()).upper()
        return name.startswith(ab) or ab == initials or ab in name

    h, a = hit(home), hit(away)
    if h and not a:
        return True
    if a and not h:
        return False
    return mkt_home < 0  # fall back to market


def team_abbr(g, home):
    return g["fav_abbr"] if (home == g.get("fav_home")) else None


def main():
    board, nfl, cfb = sys.argv[1:4]
    open_set = set()
    if "--open" in sys.argv:
        for part in sys.argv[sys.argv.index("--open") + 1].split(","):
            lo, hi = part.split("-")
            open_set |= set(range(int(lo), int(hi) + 1))
    games = parse_board(board)
    vis = {"NFL": pair_rows(json.load(open(nfl))), "CFB": pair_rows(json.load(open(cfb)))}
    res = analyze(games, vis, open_set)
    json.dump(res, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
