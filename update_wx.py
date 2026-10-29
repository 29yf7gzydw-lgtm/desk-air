#!/usr/bin/env python3
"""Fetch today's forecast from the Thai Meteorological Department's NWP API
(WRF model, data.tmd.go.th/nwpapi) and write wx.json. Runs in GitHub Actions
alongside update_air.py. Reads TMD_TOKEN, LAT, LNG from the environment
(repository secrets).

Per-variable sourcing (2026-10-24): the desk page takes NOW temp, today's
high/low and today's rain from TMD when this file is fresh and the device
is near the grid point — TMD's local model is the best-resolved source for
Thailand. History/normals stay on ERA5; yesterday/last-30 on ECMWF."""
import json
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

TOKEN = os.environ["TMD_TOKEN"]
LAT = os.environ.get("LAT", "13.76")
LNG = os.environ.get("LNG", "100.51")
ICT = ZoneInfo("Asia/Bangkok")
BASE = "https://data.tmd.go.th/nwpapi/v1/forecast/location"
# data.tmd.go.th sits behind Cloudflare, which bans the default python UA
# (error 1010) — a browser UA is required.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def get_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "accept": "application/json",
        "authorization": "Bearer " + TOKEN,
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def main():
    now = datetime.now(ICT)
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now.fromtimestamp(now.timestamp() + 86400, ICT)).strftime("%Y-%m-%d")
    hourly = get_json("%s/hourly/at?lat=%s&lon=%s&fields=tc,rh,ws10m,wd10m,rain,cond"
                      "&date=%s&hour=0&duration=24" % (BASE, LAT, LNG, today))
    hourly2 = get_json("%s/hourly/at?lat=%s&lon=%s&fields=tc,rain,cond"
                       "&date=%s&hour=0&duration=9" % (BASE, LAT, LNG, tomorrow))
    daily = get_json("%s/daily/at?lat=%s&lon=%s&fields=tc_max,tc_min"
                     "&date=%s&duration=1" % (BASE, LAT, LNG, today))

    hw = (hourly.get("WeatherForecasts") or [{}])[0]
    loc = hw.get("location") or {}
    fc = hw.get("forecasts") or []
    if not fc:
        print("no hourly forecasts")
        return 1

    now_tc, now_rh, now_ws, now_wd, best_gap = None, None, None, None, None
    rain = 0.0
    tcs = []
    for e in fc:
        t = datetime.fromisoformat(e["time"])
        d = e.get("data") or {}
        if d.get("tc") is not None:
            tcs.append(d["tc"])
            gap = abs((t - now).total_seconds())
            if best_gap is None or gap < best_gap:
                now_tc, best_gap = d["tc"], gap
                now_rh = d.get("rh")
                now_ws = d.get("ws10m")
                now_wd = d.get("wd10m")
        if d.get("rain"):
            rain += d["rain"]

    dw = (daily.get("WeatherForecasts") or [{}])[0]
    dfc = dw.get("forecasts") or []
    d0 = (dfc[0].get("data") or {}) if dfc else {}
    hi = d0.get("tc_max")
    lo = d0.get("tc_min")
    if hi is None and tcs:
        hi = max(tcs)
    if lo is None and tcs:
        lo = min(tcs)
    if now_tc is None or hi is None or lo is None:
        print("incomplete data", now_tc, hi, lo)
        return 1

    # Next 6 forecast hours after the current hour (stitched across midnight
    # from tomorrow's early hours) for the page's NEXT HOURS strip.
    fc2 = (hourly2.get("WeatherForecasts") or [{}])[0].get("forecasts") or []
    nxt = []
    for e in fc + fc2:
        t = datetime.fromisoformat(e["time"])
        if t <= now.replace(minute=0, second=0, microsecond=0):
            continue
        d = e.get("data") or {}
        if d.get("tc") is None:
            continue
        nxt.append({
            "t": t.strftime("%H:00"),
            "tc": round(d["tc"], 1),
            "rain": round(d.get("rain") or 0, 1),
            "cond": d.get("cond") or 1,
        })
        if len(nxt) >= 6:
            break

    # Day Curve: full today hourly list for the desk page (00:00-23:00, TMD).
    day = []
    for e in fc:
        t = datetime.fromisoformat(e["time"])
        d = e.get("data") or {}
        if d.get("tc") is None:
            continue
        day.append({
            "t": t.strftime("%H:00"),
            "tc": round(d["tc"], 1),
            "rain": round(d.get("rain") or 0, 1),
        })
    payload = {
        "ts": int(now.timestamp()),
        "glat": loc.get("lat"),
        "glon": loc.get("lon"),
        "now": round(now_tc, 1),
        "now_rh": (round(now_rh, 1) if now_rh is not None else None),
        "now_ws": (round(now_ws, 2) if now_ws is not None else None),
        "now_wd": (round(now_wd, 1) if now_wd is not None else None),
        "hi": round(hi, 1),
        "lo": round(lo, 1),
        "rain": round(rain, 1),
        "next": nxt,
        "day": day,
    }
    with open("wx.json", "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print("OK", json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
