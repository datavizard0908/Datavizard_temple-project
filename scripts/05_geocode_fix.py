"""為缺座標或座標有問題的寺廟補點（OSM Nominatim）。

對象：coord_status 為缺座標、預設座標，或落在別區且離地址鄉鎮界 >0.3 km，或 coord_precision=低。
查詢順序：(1) 廟名＋鄉鎮（OSM 上的寺廟 POI）；(2) 地址。
只採用落在「地址所寫鄉鎮」界線內、且類型為 POI／門牌／道路的結果。

遵守 Nominatim 使用規範：每秒最多 1 次、自訂 User-Agent、結果快取（data/raw/geocode_cache.json），
重跑不會重複查詢。只送出寺廟名稱與地址（公開資料），不送電話、負責人。

輸出：data/processed/geocode_fix.csv（編號、新座標、來源、精度、OSM 類型）
"""
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import shapefile
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
CACHE = RAW / "geocode_cache.json"
URL = "https://nominatim.openstreetmap.org/search"
UA = {"User-Agent": "TempleProject/0.1 (course data-visualization project; one-off small batch)"}
BAD = {"缺座標", "預設座標"}
FAR = {"落在界線外", "同縣市其他鄉鎮", "其他縣市"}
NAME_NOISE = re.compile(r"^(財團法人)?(台灣省|臺灣省)?(..[市縣])?(..[區鄉鎮市])?")


def load_towns():
    path = next((RAW / "town_boundary").glob("TOWN_MOI_*.shp"))
    reader = shapefile.Reader(str(path.with_suffix("")), encoding="utf-8")
    return {sr.record["COUNTYNAME"] + sr.record["TOWNNAME"]: shape(sr.shape.__geo_interface__)
            for sr in reader.iterShapeRecords()}


def precision_of(hit):
    cls, typ = hit.get("category") or hit.get("class"), hit.get("type")
    if cls == "amenity" and typ == "place_of_worship" or cls in {"building", "historic", "tourism"}:
        return "POI"
    if cls == "place" and typ == "house" or typ == "house":
        return "門牌"
    if cls == "highway":
        return "道路"
    return None  # 行政區、村里中心等太粗，不採用


def search(q, cache, last):
    if q in cache:
        return cache[q], last
    wait = 1.1 - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    r = requests.get(URL, params={"q": q, "format": "jsonv2", "countrycodes": "tw", "limit": 5,
                                  "accept-language": "zh-TW"}, headers=UA, timeout=60)
    last = time.time()
    r.raise_for_status()
    cache[q] = r.json()
    return cache[q], last


def main():
    df = pd.read_csv(PROCESSED / "temples_checked.csv", dtype={"編號": str})
    dist = pd.to_numeric(df["距地址鄉鎮界_km"], errors="coerce")
    target = df[df["coord_status"].isin(BAD) | (df["coord_status"].isin(FAR) & (dist > 0.3))
                | (df["coord_precision"] == "低")]
    if len(sys.argv) > 1:
        target = target.head(int(sys.argv[1]))  # 試跑用
    towns = load_towns()
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    last, rows = 0.0, []
    print(f"targets: {len(target)}")
    try:
        for i, rec in enumerate(target.itertuples(index=False), 1):
            town = towns.get(rec.地址鄉鎮)
            name = NAME_NOISE.sub("", rec.寺廟名稱) or rec.寺廟名稱
            addr = re.sub(r"[（(].*?[）)]|\d+鄰", "", rec.地址)
            found = None
            for via, q in (("nominatim_name", f"{name} {rec.地址鄉鎮}"), ("nominatim_addr", addr)):
                hits, last = search(q, cache, last)
                for h in hits:
                    p = Point(float(h["lon"]), float(h["lat"]))
                    prec = precision_of(h)
                    if prec and town is not None and town.contains(p):
                        found = (via, prec, h)
                        break
                if found:
                    break
            row = {"編號": rec.編號, "原coord_status": rec.coord_status}
            if found:
                via, prec, h = found
                row.update(lon=float(h["lon"]), lat=float(h["lat"]), coord_source=via,
                           coord_precision=prec, osm=f"{h.get('category')}/{h.get('type')}",
                           osm_name=h.get("display_name", "")[:80])
            rows.append(row)
            if i % 25 == 0:
                CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                print(f"{i}/{len(target)} found={sum('lon' in r for r in rows)}", flush=True)
    finally:
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    out = pd.DataFrame(rows)
    out.to_csv(PROCESSED / "geocode_fix.csv", index=False, encoding="utf-8-sig")
    print(f"done: {out['lon'].notna().sum()}/{len(out)} geocoded")
    if "coord_precision" in out:
        print(out["coord_precision"].value_counts().to_string())


if __name__ == "__main__":
    main()
