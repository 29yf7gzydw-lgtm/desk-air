#!/usr/bin/env python3
"""Precompute the desk page's historical weather stats server-side and write stats.json.
The iPad only downloads this tiny file (~3 KB) instead of the full 1940->last-year
ERA5 archive (~726 KB), which proved unreliable on an iPad Air 2.
Mirrors the page's own statsFor/windowNormals math exactly.
Reads LAT, LNG from the environment (repository secrets)."""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

LAT = os.environ.get("LAT", "13.76")
LNG = os.environ.get("LNG", "100.51")
BKK = timezone(timedelta(hours=7))

def get_json(url):
    with urllib.request.urlopen(url, timeout=120) as resp:
        return json.load(resp)

def doy_of(y, m, d):
    cum = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    leap = 1 if ((y % 4 == 0 and y % 100 != 0) or y % 400 == 0) else 0
    return cum[m - 1] + d + (leap if m > 2 else 0)

def pct(sorted_vals, p):
    if not sorted_vals:
        return None
    return sorted_vals[int(p / 100 * (len(sorted_vals) - 1))]

def main():
    now = datetime.now(BKK)
    yr = now.year - 1
    url = ("https://archive-api.open-meteo.com/v1/archive?latitude=%s&longitude=%s"
           "&start_date=1940-01-01&end_date=%d-12-31"
           "&daily=temperature_2m_max,precipitation_sum&timezone=auto" % (LAT, LNG, yr))
    a = get_json(url)
    times = a["daily"]["time"]
    maxs = a["daily"]["temperature_2m_max"]
    rains = a["daily"]["precipitation_sum"]

    def stats_for(month, day):
        mmdd = "%02d-%02d" % (month, day)
        vals, min_v, min_y, max_v, max_y = [], None, "", None, ""
        for i, t in enumerate(times):
            if t[5:] != mmdd:
                continue
            v = maxs[i]
            if v is None:
                continue
            vals.append(v)
            if min_v is None or v < min_v:
                min_v, min_y = v, t[:4]
            if max_v is None or v > max_v:
                max_v, max_y = v, t[:4]
        vals.sort()
        return {"n": len(vals), "vals": vals, "min": min_v, "minY": min_y,
                "max": max_v, "maxY": max_y, "p25": pct(vals, 25), "p75": pct(vals, 75)}

    # 30-day window normals: days [doy-30, doy-1] per year, same as the page
    t_end = doy_of(now.year, now.month, now.day)
    per_year, order = {}, []
    for i, ds in enumerate(times):
        y = int(ds[:4])
        doy = doy_of(y, int(ds[5:7]), int(ds[8:10]))
        in_win, key = False, y
        if t_end - 30 >= 1:
            in_win = t_end - 30 <= doy <= t_end - 1
        else:
            if t_end - 30 <= doy <= t_end - 1:
                in_win, key = True, y
            elif doy >= 365 + (t_end - 30):
                in_win, key = True, y + 1
        if not in_win:
            continue
        if key not in per_year:
            per_year[key] = {"sh": 0.0, "ch": 0, "sr": 0.0}
            order.append(key)
        o = per_year[key]
        if maxs[i] is not None:
            o["sh"] += maxs[i]; o["ch"] += 1
        if rains[i] is not None:
            o["sr"] += rains[i]
    ah = ar = 0.0; nh = nr = 0
    for k in order:
        o = per_year[k]
        if o["ch"] >= 25:
            ah += o["sh"] / o["ch"]; nh += 1; ar += o["sr"]; nr += 1
    wn = {"avgHigh": ah / nh, "avgRain": ar / nr, "years": nh} if nh else None

    yd = now - timedelta(days=1)
    payload = {
        "day": "%04d-%02d-%02d" % (now.year, now.month, now.day),
        "s": {"st": stats_for(now.month, now.day),
              "stY": stats_for(yd.month, yd.day),
              "wn": wn},
    }
    with open("stats.json", "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print("OK", payload["day"], "st.n =", payload["s"]["st"]["n"], "wn =", wn)
    return 0

if __name__ == "__main__":
    sys.exit(main())
