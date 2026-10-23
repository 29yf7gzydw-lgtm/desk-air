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
    hourly = get_json("%s/hourly/at?lat=%s&lon=%s&fields=tc,rain"
                      "&date=%s&hour=0&duration=24" % (BASE, LAT, LNG, today))
    daily = get_json("%s/daily/at?lat=%s&lon=%s&fields=tc_max,tc_min"
                     "&date=%s&duration=1" % (BASE, LAT, LNG, today))

    hw = (hourly.get("WeatherForecasts") or [{}])[0]
    loc = hw.get("location") or {}
    fc = hw.get("forecasts") or []
    if not fc:
        print("no hourly forecasts")
        return 1

    now_tc, best_gap = None, None
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

    payload = {
        "ts": int(now.timestamp()),
        "glat": loc.get("lat"),
        "glon": loc.get("lon"),
        "now": round(now_tc, 1),
        "hi": round(hi, 1),
        "lo": round(lo, 1),
        "rain": round(rain, 1),
    }
    with open("wx.json", "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print("OK", json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
