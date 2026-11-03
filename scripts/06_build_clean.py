"""產生清理後的分析用資料。

輸入：data/processed/temples_checked.csv（04）、data/processed/geocode_fix.csv（05）
輸出：
- data/reference/deity_normalization.csv   每種原始寫法 → 主神、信心、同祀、原鄉（審核後正式版）
- data/processed/temples_clean.csv         全部可用寺廟（給縣市／鄉鎮統計；不需要座標）
- data/processed/temples_points.geojson    其中座標有效者（給點位地圖）
- data/processed/temples_points_taipei.geojson  台北市＋新北市
- reports/cleaning_log.csv                 每筆被補值、改座標、移除座標或刪除的紀錄與原因

缺值處理：
- 主祀神祇缺值：能由廟名明確推定的就補（如「…媽廟」→天上聖母），其餘整筆刪除。
- 教別缺值：由主神與廟名推定，標 教別來源=推定。
- 座標：原始座標落在地址鄉鎮內就沿用；有問題的用 05 的補點取代；補不到的移除座標
  （該筆仍保留在 temples_clean.csv 供統計，但不進點位圖層）。
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd
import shapefile
from shapely.geometry import Point, shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deity_rules import hometown, normalize  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
REFERENCE = ROOT / "data" / "reference"
REPORTS = ROOT / "reports"
TAIPEI = ["臺北市", "新北市"]
KEEP_NEAR_BORDER_KM = 1.0  # 補點失敗時，原座標離地址鄉鎮界在此距離內仍保留並標記

# 主神缺值時，只採用廟名中意義明確的字詞
NAME_TO_DEITY = [
    (r"媽廟|媽祖|天后宮", lambda m: "天上聖母"),
    (r"福德|土地", lambda m: "福德正神"),
    (r"(.)府將軍", lambda m: f"{m.group(1)}府將軍"),
    (r"靈魂公|萬善|有應|萬應|大眾廟", lambda m: "有應公類"),
    (r"瑤池", lambda m: "瑤池金母"),
    (r"城隍", lambda m: "城隍爺"),
]
BUDDHIST = {"釋迦牟尼佛", "阿彌陀佛", "藥師佛", "地藏王菩薩", "彌勒佛", "三寶佛", "西方三聖", "觀世音菩薩"}


def deity_from_name(name):
    for pattern, make in NAME_TO_DEITY:
        m = re.search(pattern, name)
        if m:
            return make(m)
    return None


def guess_sect(deity, name):
    if deity in BUDDHIST and re.search(r"[寺院]|精舍|禪", name):
        return "佛教"
    return "道教"


def load_areas():
    """回傳 ({縣市鄉鎮村里: 多邊形}, {縣市鄉鎮: 多邊形})，來源為國土測繪中心村里界、鄉鎮界。"""
    def read(folder, pattern, key):
        path = next((ROOT / "data" / "raw" / folder).glob(pattern))
        reader = shapefile.Reader(str(path.with_suffix("")), encoding="utf-8")
        return {key(sr.record): shape(sr.shape.__geo_interface__) for sr in reader.iterShapeRecords()}
    villages = read("village_boundary", "VILLAGE_NLSC_*.shp",
                    lambda r: r["COUNTYNAME"] + r["TOWNNAME"] + r["VILLNAME"])
    towns = read("town_boundary", "TOWN_MOI_*.shp", lambda r: r["COUNTYNAME"] + r["TOWNNAME"])
    return villages, towns


def parse_village(addr, town, villages):
    """地址中鄉鎮之後的村里名，需存在於村里界資料。"""
    if not isinstance(town, str):
        return None
    county = town[:3]
    rest = addr[len(county):] if addr.startswith(county) else addr
    rest = rest[len(town) - 3:] if rest.startswith(town[3:]) else None
    if not rest:
        return None
    for n in (4, 3, 2):
        if rest[n - 1:n] in ("村", "里") and town + rest[:n] in villages:
            return town + rest[:n]
    return None


NAME_NOISE = re.compile(r"^(財團法人)?(台灣省|臺灣省)?(..[市縣])?(..[區鄉鎮市])?")
VILLAGE_BUFFER_DEG = 0.003  # 約 300 m，容許村里界與 OSM 點的小誤差


def validate_fix(fix, df, villages):
    """剔除可疑的補點：廟名查到但 OSM 名稱不符、點不在地址村里內，或多間廟共用同一點。"""
    fix = fix.dropna(subset=["lon"]).copy()
    info = df.set_index("編號")[["寺廟名稱", "地址", "地址鄉鎮"]]
    fix = fix[fix.index.isin(info.index)]
    key = fix["lon"].round(5).astype(str) + "," + fix["lat"].round(5).astype(str)
    shared = key.map(key.value_counts()) > 1
    reasons = {}
    for sid, r in fix.iterrows():
        name = NAME_NOISE.sub("", info.at[sid, "寺廟名稱"]) or info.at[sid, "寺廟名稱"]
        osm_name = str(r["osm_name"]).split(",")[0].strip()
        vill = parse_village(info.at[sid, "地址"], info.at[sid, "地址鄉鎮"], villages)
        if shared[sid]:
            reasons[sid] = "多間廟共用同一 OSM 點"
        elif r["coord_source"] == "nominatim_name" and name not in osm_name:
            reasons[sid] = f"OSM 名稱不符（{osm_name}）"
        elif vill and not villages[vill].buffer(VILLAGE_BUFFER_DEG).contains(Point(r["lon"], r["lat"])):
            reasons[sid] = f"不在地址村里內（{osm_name}）"
    return fix.drop(index=list(reasons)), reasons


def to_geojson(df, path):
    props = [c for c in df.columns if c not in ("lon", "lat")]
    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(r["lon"], 6), round(r["lat"], 6)]},
        "properties": {k: (None if pd.isna(r[k]) else r[k]) for k in props},
    } for r in df.to_dict("records")]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
                    encoding="utf-8")


def main():
    df = pd.read_csv(PROCESSED / "temples_checked.csv", dtype={"編號": str})
    fix = pd.read_csv(PROCESSED / "geocode_fix.csv", dtype={"編號": str}).set_index("編號")
    log = []

    # 主神
    norm = df["主祀神祇"].map(normalize).apply(pd.Series)
    df = pd.concat([df, norm], axis=1)
    df["主神來源"] = "原始資料"
    for i in df.index[df["主神"].isna()]:
        guess = deity_from_name(df.at[i, "寺廟名稱"])
        if guess:
            df.loc[i, ["主神", "主神_信心", "主神來源"]] = [guess, "中", "由廟名推定"]
            log.append((df.at[i, "編號"], "補值", "主神", f"由廟名推定為 {guess}"))
    for i in df.index[df["主神"].isna()]:
        log.append((df.at[i, "編號"], "刪除", "整筆", f"主祀神祇缺值且廟名無法推定（{df.at[i, '寺廟名稱']}）"))
    df = df[df["主神"].notna()].copy()

    ht = [hometown(c, k) for c, k in zip(df["主神"], df["主神_信心"])]
    df["原鄉"] = [h[0] for h in ht]
    df["原鄉層級"] = [h[1] for h in ht]

    # 教別
    df["教別來源"] = "原始資料"
    for i in df.index[df["教別"].isna()]:
        guess = guess_sect(df.at[i, "主神"], df.at[i, "寺廟名稱"])
        df.loc[i, ["教別", "教別來源"]] = [guess, "推定"]
        log.append((df.at[i, "編號"], "補值", "教別", f"由主神與廟名推定為 {guess}"))

    # 座標
    villages, towns = load_areas()
    fix, rejected = validate_fix(fix, df, villages)
    for sid, why in rejected.items():
        log.append((sid, "不採用補點", "座標", why))
    df["lon"], df["lat"] = df["WGS84X"], df["WGS84Y"]
    df["coord_source"] = "原始資料"
    df["coord_flag"] = ""
    df.loc[df["coord_status"] == "鄰區_近邊界", "coord_flag"] = "近鄉鎮界"
    df.loc[df["coord_precision"] == "低", "coord_flag"] = "低精度"
    dist = pd.to_numeric(df["距地址鄉鎮界_km"], errors="coerce")
    for i in df.index:
        sid, status = df.at[i, "編號"], df.at[i, "coord_status"]
        if sid in fix.index and pd.notna(fix.at[sid, "lon"]):
            df.loc[i, ["lon", "lat", "coord_source", "coord_precision", "coord_flag"]] = [
                fix.at[sid, "lon"], fix.at[sid, "lat"], fix.at[sid, "coord_source"],
                fix.at[sid, "coord_precision"], ""]
            log.append((sid, "改座標", "座標", f"{status} → {fix.at[sid, 'coord_source']}（{fix.at[sid, 'coord_precision']}）"))
        elif status in ("ok", "鄰區_近邊界"):
            continue
        elif status in ("落在界線外", "同縣市其他鄉鎮", "其他縣市") and dist[i] <= KEEP_NEAR_BORDER_KM:
            df.at[i, "coord_flag"] = "近鄉鎮界"
        else:
            df.loc[i, ["lon", "lat", "coord_source", "coord_flag"]] = [None, None, None, ""]

    # 仍無座標者：退到地址中村里的代表點，再退到鄉鎮代表點；標為概略位置，分析時排除
    for i in df.index[df["lon"].isna()]:
        sid, town = df.at[i, "編號"], df.at[i, "地址鄉鎮"]
        vill = parse_village(df.at[i, "地址"], town, villages)
        area, source = (villages[vill], "村里中心") if vill else (towns.get(town), "鄉鎮中心")
        if area is None:
            log.append((sid, "移除座標", "座標", f"{df.at[i, 'coord_status']}，補點失敗且無法對應行政區"))
            continue
        p = area.representative_point()
        df.loc[i, ["lon", "lat", "coord_source", "coord_precision", "coord_flag"]] = [
            p.x, p.y, source, "概略", "概略位置"]
        log.append((sid, "概略座標", "座標", f"{df.at[i, 'coord_status']}，補點失敗 → {source}"))

    df["縣市"] = df["行政區"]
    df["鄉鎮市區"] = [t[len(c):] if isinstance(t, str) else None for t, c in zip(df["地址鄉鎮"], df["縣市"])]
    cols = ["編號", "寺廟名稱", "縣市", "鄉鎮市區", "地址", "主祀神祇", "主神", "主神_信心", "主神來源", "同祀",
            "多神並列", "原鄉", "原鄉層級", "教別", "教別來源", "登記別", "lon", "lat", "coord_source",
            "coord_precision", "coord_flag"]
    clean = df[cols].rename(columns={"主祀神祇": "主祀神祇_原始"})
    clean.to_csv(PROCESSED / "temples_clean.csv", index=False, encoding="utf-8-sig")
    points = clean[clean["lon"].notna()].copy()
    points[["lon", "lat"]] = points[["lon", "lat"]].astype(float)
    to_geojson(points, PROCESSED / "temples_points.geojson")
    to_geojson(points[points["縣市"].isin(TAIPEI)], PROCESSED / "temples_points_taipei.geojson")

    REFERENCE.mkdir(parents=True, exist_ok=True)
    table = df[df["主神來源"] == "原始資料"].groupby("主祀神祇").agg(
        次數=("編號", "size"), 主神=("主神", "first"), 主神_信心=("主神_信心", "first"),
        同祀=("同祀", "first"), 原鄉=("原鄉", "first"), 原鄉層級=("原鄉層級", "first"),
    ).sort_values("次數", ascending=False).rename_axis("原始寫法").reset_index()
    table.to_csv(REFERENCE / "deity_normalization.csv", index=False, encoding="utf-8-sig")

    pd.DataFrame(log, columns=["編號", "動作", "欄位", "原因"]).to_csv(
        REPORTS / "cleaning_log.csv", index=False, encoding="utf-8-sig")

    # 網站用：全台點位與摘要數字（不含原始資料與個資）
    site_data = ROOT / "site" / "data"
    site_data.mkdir(parents=True, exist_ok=True)
    site_cols = ["編號", "寺廟名稱", "縣市", "鄉鎮市區", "地址", "主祀神祇_原始", "主神", "同祀", "原鄉", "原鄉層級",
                 "coord_source", "coord_precision", "coord_flag", "lon", "lat"]
    to_geojson(points[site_cols], site_data / "temples.geojson")
    (site_data / "temples_taipei.geojson").unlink(missing_ok=True)
    fetch = json.loads((ROOT / "data" / "raw" / "temple.fetch.json").read_text(encoding="utf-8"))
    actions = pd.Series([a for _, a, _, _ in log]).value_counts().to_dict()
    tp = clean[clean["縣市"].isin(TAIPEI)]
    summary = {
        "fetched_at_utc": fetch["fetched_at_utc"], "source_modified": fetch["modified_date"],
        "raw_rows": 12427, "clean_rows": len(clean), "dropped_rows": 12427 - len(clean),
        "points": len(points), "coord_removed": actions.get("移除座標", 0),
        "coord_approx": actions.get("概略座標", 0),
        "coord_fixed": actions.get("改座標", 0), "values_inferred": actions.get("補值", 0),
        "taipei_rows": len(tp), "taipei_points": int(tp["lon"].notna().sum()),
        "taipei_fixed": int(tp["coord_source"].fillna("").str.startswith("nominatim").sum()),
    }
    (site_data / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"clean rows: {len(clean)} (dropped {12427 - len(clean)}); points: {len(points)}")
    print(f"taipei: {len(tp)} rows, {tp['lon'].notna().sum()} points")
    print(pd.Series([a for _, a, _, _ in log]).value_counts().to_string())
    print(clean["coord_source"].value_counts(dropna=False).to_string())
    print("原鄉層級（台北）:", tp["原鄉層級"].value_counts().to_dict())
    print(tp[tp["原鄉"] != ""].groupby(["原鄉層級", "主神"]).size().to_string())


if __name__ == "__main__":
    main()
