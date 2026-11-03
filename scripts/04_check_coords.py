"""座標落區檢查：把每筆寺廟座標套內政部鄉鎮市區界，與地址中的縣市＋鄉鎮比對。

界線資料：data.gov.tw #7441 鄉鎮市區界線(TWD97經緯度)，國土測繪中心。
下載後解壓 TOWN_MOI_*.{shp,shx,dbf,prj,cpg} 到 data/raw/town_boundary/。
TWD97 經緯度與 WGS84 差距在公分級，直接比對。

輸出：
- data/processed/temples_checked.csv  temples.csv 加上 coord_status、落點縣市鄉鎮、距地址鄉鎮界 km
- reports/coord_check_summary.csv     各縣市 × coord_status 筆數
- reports/coord_check_taipei.csv      台北市＋新北市非 ok 者，供人工確認
"""
import re
from pathlib import Path

import pandas as pd
import shapefile
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
TAIPEI = ["臺北市", "新北市"]
NEAR_BORDER_KM = 0.3  # 落在鄰區但離地址鄉鎮界這麼近，視為邊界誤差
KM_PER_DEG = 111.0    # 粗估，台灣緯度下經度方向約 101 km/deg，取整數做門檻足夠
# 原始資料中雲林、台南、屏東、台中的廟共用這一點（台北市中正區），判定為系統預設值
PLACEHOLDER = (121.5195, 25.0421)


def load_towns():
    path = next((RAW / "town_boundary").glob("TOWN_MOI_*.shp"))
    reader = shapefile.Reader(str(path.with_suffix("")), encoding="utf-8")
    geoms, keys = [], []
    for sr in reader.iterShapeRecords():
        geoms.append(shape(sr.shape.__geo_interface__))
        keys.append(sr.record["COUNTYNAME"] + sr.record["TOWNNAME"])
    return geoms, keys


def parse_town(addr, county, known):
    """取地址中的鄉鎮；優先用界線資料的鄉鎮名單比對（避免「前鎮區」被切成「前鎮」）。"""
    rest = addr[len(county):] if addr.startswith(county) else addr
    for n in (4, 3, 2):
        if county + rest[:n] in known:
            return county + rest[:n]
    m = re.match(r"^(.{1,4}?[區鄉鎮市])", rest)
    return county + m.group(1) if m else None


def main():
    df = pd.read_csv(PROCESSED / "temples.csv", dtype={"編號": str, "統一編號": str})
    geoms, keys = load_towns()
    tree = STRtree(geoms)
    by_key = dict(zip(keys, geoms))

    df["地址鄉鎮"] = [parse_town(a, c, by_key) for a, c in zip(df["地址"], df["行政區"])]
    status, hit_town, dist = [], [], []
    for x, y, want in zip(df["WGS84X"], df["WGS84Y"], df["地址鄉鎮"]):
        if pd.isna(x) or x == 0:
            status.append("缺座標"); hit_town.append(None); dist.append(None)
            continue
        if (round(x, 4), round(y, 4)) == PLACEHOLDER:
            status.append("預設座標"); hit_town.append(None); dist.append(None)
            continue
        p = Point(x, y)
        hits = [keys[i] for i in tree.query(p, predicate="within")]
        got = hits[0] if hits else None
        hit_town.append(got)
        target = by_key.get(want)
        d = round(target.distance(p) * KM_PER_DEG, 2) if target is not None else None
        dist.append(d)
        if target is None:
            status.append("地址鄉鎮查無界線")  # 舊名或錯字，需人工
        elif got == want:
            status.append("ok")
        elif got is None:
            status.append("落在界線外")  # 海上或範圍外
        elif d is not None and d <= NEAR_BORDER_KM:
            status.append("鄰區_近邊界")
        elif got[:3] == want[:3]:
            status.append("同縣市其他鄉鎮")
        else:
            status.append("其他縣市")
    df["落點鄉鎮"] = hit_town
    df["距地址鄉鎮界_km"] = dist
    df["coord_status"] = status
    # 小數 ≤3 位（約百公尺至公里級）視為低精度；其餘不代表到門牌，只是沒有明顯截斷
    decimals = df["WGS84X"].map(lambda v: len(repr(v).split(".")[1]) if pd.notna(v) and "." in repr(v) else None)
    df["coord_precision"] = decimals.map(lambda n: None if pd.isna(n) else ("低" if n <= 3 else "未知"))
    df.to_csv(PROCESSED / "temples_checked.csv", index=False, encoding="utf-8-sig")

    summary = pd.crosstab(df["行政區"], df["coord_status"], margins=True, margins_name="合計")
    summary.to_csv(REPORTS / "coord_check_summary.csv", encoding="utf-8-sig")
    tp = df[df["行政區"].isin(TAIPEI) & ((df["coord_status"] != "ok") | (df["coord_precision"] == "低"))]
    cols = ["編號", "寺廟名稱", "主祀神祇", "地址", "WGS84X", "WGS84Y", "落點鄉鎮", "距地址鄉鎮界_km",
            "coord_status", "coord_precision"]
    tp.sort_values(["coord_status", "距地址鄉鎮界_km"], ascending=[True, False])[cols].to_csv(
        REPORTS / "coord_check_taipei.csv", index=False, encoding="utf-8-sig")

    print(df["coord_status"].value_counts().to_string())
    print("低精度：", (df["coord_precision"] == "低").sum())
    print(summary.loc[TAIPEI + ["合計"]].to_string())
    unknown = df.loc[df["coord_status"] == "地址鄉鎮查無界線", "地址鄉鎮"].value_counts()
    if len(unknown):
        print("查無界線的地址鄉鎮：", unknown.head(20).to_dict())


if __name__ == "__main__":
    main()
