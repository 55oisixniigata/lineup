#!/usr/bin/env python3
"""
lineup stats.json 自動生成スクリプト
NPBファームからオイシックス成績を取得して stats.json を生成する。
GitHub Actions で毎朝 6:00 JST に自動実行。
"""

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

YEAR        = date.today().year
BASE        = "https://npb.jp"
OISIX_CODE  = "a"   # スコアURLのチームコード（アルビレックス）
OISIX_MARK  = "Ｏ"  # 成績テーブル内の略号（全角）
OUT_FILE    = Path(__file__).parent.parent / "stats.json"

TEAM_CODE = {
    "e": "楽天", "f": "日本ハム", "m": "ロッテ", "s": "ヤクルト",
    "g": "巨人", "db": "DeNA",   "l": "西武",   "d": "中日",
    "h": "ソフトバンク", "b": "オリックス", "c": "広島", "t": "阪神",
    "v": "ハヤテ",
}
HEADER_TO_TEAM = {
    "対日": "日本ハム", "対楽": "楽天", "対ロ": "ロッテ", "対ヤ": "ヤクルト",
}

def get(url):
    headers = {"User-Agent": "lineup-stats/1.0"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return BeautifulSoup(r.text, "html.parser")

def clean_name(raw):
    return re.sub(r"[\s　]+", "", re.sub(r"\(.+?\)", "", raw))

def tbl_rows(tbl):
    return [
        [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        for tr in tbl.find_all("tr")
    ]

def ip_to_float(s):
    s = s.strip()
    plus = s.count("+")
    digits = re.sub(r"[^\d.]", "", s)
    if not digits:
        return 0.0
    if "." in digits:
        w, f = digits.split(".", 1)
        return int(w) + int(f[0] if f else 0) / 3
    return int(digits) + plus / 3

def parse_batting(soup):
    tbl = soup.find("table")
    if not tbl: return [], []
    all_p, oisix = [], []
    for cells in tbl_rows(tbl)[1:]:
        if len(cells) < 14: continue
        name_raw = cells[1]
        is_o = f"({OISIX_MARK})" in name_raw
        name = clean_name(name_raw)
        if not name: continue
        try:
            p = {"name": name, "avg": cells[2],
                 "ab": int(cells[5]) if cells[5].isdigit() else 0,
                 "hr": int(cells[10]) if cells[10].isdigit() else 0,
                 "rbi": int(cells[12]) if cells[12].isdigit() else 0,
                 "sb": int(cells[13]) if cells[13].isdigit() else 0}
        except (ValueError, IndexError): continue
        all_p.append(p)
        if is_o: oisix.append(p)
    return all_p, oisix

def parse_pitching(soup):
    tbl = soup.find("table")
    if not tbl: return [], []
    all_p, oisix = [], []
    for cells in tbl_rows(tbl)[1:]:
        if len(cells) < 14: continue
        name_raw = cells[1]
        is_o = f"({OISIX_MARK})" in name_raw
        name = clean_name(name_raw)
        if not name: continue
        try:
            so_val = int(cells[-5]) if len(cells) >= 5 and cells[-5].isdigit() else 0
            p = {"name": name, "era": cells[2],
                 "apps": int(cells[3]) if cells[3].isdigit() else 0,
                 "wins": int(cells[4]) if cells[4].isdigit() else 0,
                 "losses": int(cells[5]) if cells[5].isdigit() else 0,
                 "saves": int(cells[6]) if cells[6].isdigit() else 0,
                 "ip": cells[12], "so": so_val}
        except (ValueError, IndexError): continue
        all_p.append(p)
        if is_o: oisix.append(p)
    return all_p, oisix

def parse_standings(soup):
    tbl = soup.find("table")
    if not tbl: return {}, {}
    rows = tbl_rows(tbl)
    if not rows: return {}, {}
    headers = rows[0]
    oisix_data, h2h = {}, {}
    for i, cells in enumerate(rows[1:], start=1):
        if not cells or ("オイシックス" not in cells[0] and "新潟" not in cells[0]):
            continue
        try:
            oisix_data = {
                "rank": i,
                "wins": int(cells[2]) if len(cells) > 2 and cells[2].isdigit() else 0,
                "losses": int(cells[3]) if len(cells) > 3 and cells[3].isdigit() else 0,
                "ties": int(cells[4]) if len(cells) > 4 and cells[4].isdigit() else 0,
                "pct": cells[5] if len(cells) > 5 else ".000",
                "home": cells[7] if len(cells) > 7 else "",
                "road": cells[8] if len(cells) > 8 else "",
            }
            for j, hdr in enumerate(headers):
                if hdr in HEADER_TO_TEAM and j < len(cells):
                    score = cells[j]
                    if re.search(r"\d", score):
                        h2h[HEADER_TO_TEAM[hdr]] = score
        except (ValueError, IndexError): pass
        break
    return oisix_data, h2h

def compute_ranks(all_bat, oisix_bat, all_pit, oisix_pit):
    def rank_of(name, players, key, asc=False):
        try:
            valid = [p for p in players if p.get(key) is not None]
            srt = sorted(valid, key=lambda x: float(x[key]) if isinstance(x[key], str) else x[key], reverse=not asc)
            for i, p in enumerate(srt, 1):
                if p["name"] == name: return i
        except: pass
        return None

    ranks = {}
    for p in oisix_bat:
        n = p["name"]
        ranks[n] = {"avg_rank": rank_of(n, all_bat, "avg"),
                    "hr_rank":  rank_of(n, all_bat, "hr"),
                    "rbi_rank": rank_of(n, all_bat, "rbi"),
                    "sb_rank":  rank_of(n, all_bat, "sb")}
    for p in oisix_pit:
        n = p["name"]
        if n not in ranks: ranks[n] = {}
        ranks[n]["era_rank"] = rank_of(n, all_pit, "era", asc=True)
        ranks[n]["so_rank"]  = rank_of(n, all_pit, "so")
    return ranks

def find_recent_games(n=10):
    games = []
    today = date.today()
    months = []
    cur = today
    for _ in range(3):
        months.append(cur.month)
        cur = (cur.replace(day=1) - timedelta(days=1))

    for month in months:
        url = f"{BASE}/farm/{YEAR}/schedule_{month:02d}_detail.html"
        try:
            soup = get(url)
        except Exception as e:
            print(f"  schedule error ({month}): {e}")
            continue
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "scores_farm" not in href: continue
            m = re.search(r"scores_farm/\d+/(\d{2})(\d{2})/([^-/]+)-([^-/]+)-(\d+)/", href)
            if not m: continue
            mm, dd, t1, t2, num = m.groups()
            mm, dd = int(mm), int(dd)
            if t1 != OISIX_CODE and t2 != OISIX_CODE: continue
            try:
                gdate = date(YEAR, mm, dd)
            except ValueError: continue
            if gdate >= today: continue
            text = a.get_text(" ", strip=True)
            if "中止" in text: continue
            sm = re.search(r"(\d+)\s*[-−]\s*(\d+)", text)
            if not sm: continue
            s1, s2 = int(sm.group(1)), int(sm.group(2))
            # URL形式: HOME-AWAY-NUM
            if t2 == OISIX_CODE:
                oisix_s, opp_s, opp_code, is_home = s2, s1, t1, False
            else:
                oisix_s, opp_s, opp_code, is_home = s1, s2, t2, True
            result = "W" if oisix_s > opp_s else ("L" if oisix_s < opp_s else "T")
            games.append({
                "date": f"{YEAR}-{mm:02d}-{dd:02d}",
                "opponent": TEAM_CODE.get(opp_code, opp_code),
                "oisixScore": oisix_s, "oppScore": opp_s,
                "result": result, "isHome": is_home,
                "box_url": f"{BASE}{href}box.html",
            })
        if len(games) >= n: break

    games.sort(key=lambda g: g["date"], reverse=True)
    return games[:n]

def match_name(short, full_names):
    if not short: return None
    c = [n for n in full_names if n.startswith(short)]
    return c[0] if len(c) == 1 else None

def scrape_box(game, oisix_names):
    try:
        soup = get(game["box_url"])
    except Exception as e:
        print(f"  box error: {e}")
        return {}, {}
    batting, pitching = {}, {}
    for tbl in soup.find_all("table"):
        rows = tbl_rows(tbl)
        if not rows: continue
        headers = rows[0]
        if "打数" in headers and "安打" in headers:
            for cells in rows[1:]:
                if len(cells) < 7: continue
                short = re.sub(r"[\s　]+", "", cells[2]) if len(cells) > 2 else ""
                full = match_name(short, oisix_names)
                if not full: continue
                try:
                    batting[full] = {
                        "ab": int(cells[3]) if cells[3].isdigit() else 0,
                        "h":  int(cells[5]) if cells[5].isdigit() else 0,
                        "rbi": int(cells[6]) if cells[6].isdigit() else 0,
                    }
                except (ValueError, IndexError): pass
        elif "投球回" in headers and "三振" in headers:
            for cells in rows[1:]:
                if len(cells) < 8: continue
                short = re.sub(r"[\s　]+", "", cells[1]) if len(cells) > 1 else ""
                full = match_name(short, oisix_names)
                if not full: continue
                try:
                    pitching[full] = {
                        "ip": ip_to_float(cells[4]),
                        "so": int(cells[-5]) if cells[-5].isdigit() else 0,
                        "er": int(cells[-1]) if cells[-1].isdigit() else 0,
                    }
                except (ValueError, IndexError): pass
    return batting, pitching

def aggregate_batting(games_stats, names, n=5):
    result = {}
    for name in names:
        ab = h = rbi = g = 0
        for gs in games_stats[:n]:
            if name in gs["batting"]:
                s = gs["batting"][name]
                ab += s.get("ab", 0); h += s.get("h", 0)
                rbi += s.get("rbi", 0); g += 1
        if g > 0 and ab > 0:
            result[name] = {"games": g, "ab": ab, "h": h, "rbi": rbi,
                            "avg": f"{h/ab:.3f}"}
    return result

def aggregate_pitching(games_stats, names, n=3):
    result = {}
    for name in names:
        tip = ter = tso = apps = 0.0
        for gs in games_stats:
            if name in gs["pitching"]:
                s = gs["pitching"][name]
                tip += s.get("ip", 0); ter += s.get("er", 0)
                tso += s.get("so", 0); apps += 1
            if apps >= n: break
        if apps > 0:
            era = (ter * 9 / tip) if tip > 0 else 0.0
            w = int(tip); fr = round((tip - w) * 3)
            result[name] = {"apps": int(apps), "ip": f"{w}.{fr}" if fr else f"{w}.0",
                            "er": int(ter), "so": int(tso), "era": f"{era:.2f}"}
    return result

def recent_context(games):
    if not games: return None, None, ""
    st = games[0]["result"]
    cnt = sum(1 for g in games if g["result"] == st and st in "WL")
    # 連続チェック（途切れたらストップ）
    real_cnt = 0
    for g in games:
        if g["result"] == st and st in "WL": real_cnt += 1
        else: break
    streak = {"type": st, "count": real_cnt} if real_cnt >= 2 and st in "WL" else None
    today = date.today()
    this_m = f"{today.year}-{today.month:02d}"
    mg = [g for g in games if g["date"].startswith(this_m)]
    month_record = {
        "wins":   sum(1 for g in mg if g["result"] == "W"),
        "losses": sum(1 for g in mg if g["result"] == "L"),
        "ties":   sum(1 for g in mg if g["result"] == "T"),
    }
    return streak, month_record, "".join(g["result"] for g in games[:5])

def main():
    print("=== lineup stats.json 生成 ===")

    print("1. 打撃成績取得中...")
    all_bat, oisix_bat = parse_batting(get(f"{BASE}/bis/{YEAR}/stats/bat_2e.html"))
    oisix_bat_names = {p["name"] for p in oisix_bat}
    print(f"   オイシックス打者: {len(oisix_bat)}名")

    print("2. 投手成績取得中...")
    all_pit, oisix_pit = parse_pitching(get(f"{BASE}/bis/{YEAR}/stats/pit_2e.html"))
    oisix_pit_names = {p["name"] for p in oisix_pit}
    print(f"   オイシックス投手: {len(oisix_pit)}名")

    all_oisix_names = oisix_bat_names | oisix_pit_names

    print("3. リーグランク計算中...")
    league_ranks = compute_ranks(all_bat, oisix_bat, all_pit, oisix_pit)

    print("4. チーム成績取得中...")
    oisix_team, h2h = parse_standings(get(f"{BASE}/bis/{YEAR}/stats/std_2e.html"))
    print(f"   {oisix_team.get('wins')}勝{oisix_team.get('losses')}敗 ({oisix_team.get('rank')}位)")

    print("5. 試合スケジュール検索中...")
    recent_games = find_recent_games(n=10)
    print(f"   {len(recent_games)}試合取得")

    print("6. ボックススコア取得中（直近5試合）...")
    games_stats = []
    for g in recent_games[:5]:
        print(f"   {g['date']} vs {g['opponent']}...", end=" ", flush=True)
        b, p = scrape_box(g, all_oisix_names)
        games_stats.append({"batting": b, "pitching": p})
        print(f"打者{len(b)}名, 投手{len(p)}名")

    print("7. 直近成績集計中...")
    recent_bat = aggregate_batting(games_stats, oisix_bat_names)
    recent_pit = aggregate_pitching(games_stats, oisix_pit_names)

    streak, month_record, recent5 = recent_context(recent_games)

    for p in oisix_bat:
        if p["name"] in recent_bat: p["recent"] = recent_bat[p["name"]]
    for p in oisix_pit:
        if p["name"] in recent_pit: p["recent"] = recent_pit[p["name"]]

    stats = {
        "updated": date.today().isoformat(),
        "oisix": oisix_team,
        "headToHead": h2h,
        "batting": oisix_bat,
        "pitching": oisix_pit,
        "leagueRanks": league_ranks,
        "recent": {
            "streak": streak,
            "monthRecord": month_record,
            "recent5": recent5,
            "lastGames": [
                {"opponent": g["opponent"], "oisixScore": g["oisixScore"],
                 "oppScore": g["oppScore"], "result": g["result"]}
                for g in recent_games[:8]
            ],
        },
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完了: {OUT_FILE}")
    print(f"   直近: {recent5}  連勝/連敗: {streak}")

if __name__ == "__main__":
    main()
