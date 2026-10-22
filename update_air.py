#!/usr/bin/env python3
"""Fetch the nearest fresh PM2.5 station (OpenAQ / Thai PCD via Air4Thai),
compute a US AQI, and write air.json. Runs in GitHub Actions.
Reads OPENAQ_KEY, LAT, LNG from the environment (repository secrets)."""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

KEY = os.environ["OPENAQ_KEY"]
LAT = os.environ.get("LAT", "13.76")
LNG = os.environ.get("LNG", "100.51")
MAX_AGE = 3 * 3600


def get_json(url):
    req = urllib.request.Request(url, headers={"X-API-Key": KEY})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def parse_ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def fresh(ts):
    age = time.time() - ts
    return 0 <= age < MAX_AGE or -3600 < age < 0


def aqi_sub(c, bp):
    aqi = [0, 50, 100, 150, 200, 300, 500]
    if c is None or c < 0 or c > bp[-1]:
        return None
    for i in range(1, len(bp)):
        if c <= bp[i]:
            return (aqi[i] - aqi[i - 1]) / (bp[i] - bp[i - 1]) * (c - bp[i - 1]) + aqi[i - 1]
    return None


def compute_aqi(m):
    subs = []

    def add(val, bp, conv=None):
        if val is None:
            return
        v = aqi_sub(conv(val) if conv else val, bp)
        if v is not None:
            subs.append(v)

    add(m.get("pm25"), [0, 12.0, 35.4, 55.4, 150.4, 250.4, 500.4])
    add(m.get("pm10"), [0, 54, 154, 254, 354, 424, 604])
    add(m.get("o3"), [0, 54, 70, 85, 105, 200], lambda x: x * 0.5094)
    add(m.get("no2"), [0, 53, 100, 360, 649, 1249, 2049], lambda x: x * 0.5314)
    add(m.get("so2"), [0, 35, 75, 185, 304], lambda x: x * 0.3817)
    add(m.get("co"), [0, 4.4, 9.4, 12.4, 15.4, 30.4, 50.4], lambda x: x * 0.0008729)
    return round(max(subs)) if subs else None


def main():
    locs = get_json("https://api.openaq.org/v3/locations?coordinates=%s,%s"
                    "&radius=25000&limit=50" % (LAT, LNG))
    cands = []
    for loc in locs.get("results", []):
        sensors = loc.get("sensors") or []
        if not any((s.get("parameter") or {}).get("name") == "pm25" for s in sensors):
            continue
        last = (loc.get("datetimeLast") or {}).get("utc")
        if not last or not fresh(parse_ts(last)):
            continue
        cands.append(loc)
    cands.sort(key=lambda l: l.get("distance") or 99999)
    if not cands:
        print("no fresh pm25 station")
        return 1
    for loc in cands[:3]:
        smap = {}
        for s in loc.get("sensors") or []:
            p = s.get("parameter") or {}
            if p.get("name"):
                smap[s["id"]] = p["name"]
        latest = get_json("https://api.openaq.org/v3/locations/%s/latest" % loc["id"])
        m, newest = {}, 0
        for e in latest.get("results", []):
            name = smap.get(e.get("sensorsId"))
            dt = (e.get("datetime") or {}).get("utc")
            if not name or not dt or e.get("value") is None or e["value"] < 0:
                continue
            ts = parse_ts(dt)
            if not fresh(ts):
                continue
            m[name] = e["value"]
            newest = max(newest, ts)
        if "pm25" not in m:
            continue
        payload = {
            "pm": round(m["pm25"]),
            "aqi": compute_aqi(m),
            "station": loc.get("name") or "",
            "km": round((loc.get("distance") or 0) / 100) / 10,
            "ts": int(newest),
        }
        with open("air.json", "w", encoding="utf-8") as f:
            json.dump(payload, f)
        print("OK", json.dumps(payload))
        return 0
    print("no station with fresh pm25 in latest")
    return 1


if __name__ == "__main__":
    sys.exit(main())
