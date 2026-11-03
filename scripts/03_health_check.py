"""資料體檢：#8203 寺廟資料。

讀 data/raw/temple_raw.csv，輸出到 reports/：
- fields_missing.csv          各欄缺值比例
- counts_by_county.csv        各縣市筆數
- deity_spellings_top100.csv  主祀神祇寫法前 100 名
- deity_normalization_draft.csv  所有寫法的正規化草稿（待團隊人工審核）
- taipei_address_sample.csv   台北市＋新北市地址抽樣 20 筆與座標檢查
- coord_flags_taipei.csv      台北市＋新北市座標可疑點
- health_check.md             摘要
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
REPORTS = ROOT / "reports"
TAIPEI = ["臺北市", "新北市"]
SEED = 8203

# 初版草稿規則，只用於體檢報告。審核後的正式規則在 deity_rules.py（05 清理用）。
# (正則, 正規名稱, 信心) —— 依序比對，第一個命中者為準。
DEITY_RULES = [
    (r"福德|土地公|土地爺|伯公", "福德正神", "高"),
    (r"天上聖母|媽祖|天后|天妃|湄洲", "天上聖母", "高"),
    (r"釋迦|牟尼|摩尼", "釋迦牟尼佛", "高"),
    (r"觀世音|觀音|千手千眼", "觀世音菩薩", "高"),
    (r"玄天上帝|北極|真武|上帝公|玄天", "玄天上帝", "高"),
    (r"關聖|關帝|關公|文衡|協天|恩主公", "關聖帝君", "高"),
    (r"保生大帝|大道公|吳真人", "保生大帝", "高"),
    (r"清水祖師|蓬萊祖師|清水巖", "清水祖師", "高"),
    (r"^祖師公$|^祖師爺$", "清水祖師", "低：祖師公也可能指其他祖師"),
    (r"開漳聖王|陳聖王|聖王公", "開漳聖王", "中：聖王公也可能指其他聖王"),
    (r"三山國王", "三山國王", "高"),
    (r"廣澤尊王|郭聖王|聖王郭", "廣澤尊王", "高"),
    (r"開[台臺]聖王|鄭成功|延平郡王|國姓", "延平郡王", "高"),
    (r"中壇元帥|太子爺|三太子|哪吒|太子元帥", "中壇元帥", "高"),
    (r"瑤池金母|西王金母|王母娘娘|金母", "瑤池金母", "高"),
    (r"玉皇|天公", "玉皇大帝", "高"),
    (r"城隍", "城隍爺", "高"),
    (r"濟公|濟顛", "濟公活佛", "高"),
    (r"彌勒", "彌勒佛", "高"),
    (r"地藏", "地藏王菩薩", "高"),
    (r"神農|五[谷穀]|先帝爺", "神農大帝", "高"),
    (r"三官|三界公", "三官大帝", "高"),
    (r"孚佑|呂洞賓|純陽|呂祖", "孚佑帝君", "高"),
    (r"文昌", "文昌帝君", "高"),
    (r"張公聖君|法主", "法主公", "高"),
    (r"保儀|尪公", "保儀尊王", "中：保儀尊王與保儀大夫是否合併待審"),
    (r"靈安尊王|青山王", "靈安尊王", "高"),
    (r"萬應|萬善|有應公|百姓公|大眾爺|大墓公|金斗|聖公媽", "有應公類", "中：分類用，非單一神祇"),
    (r"義民", "義民爺", "高"),
    (r"張天師|張府天師|廣信天師", "張天師", "中：廣信天師是否同尊待審"),
    (r"^(.)府(千歲|王爺|元帥)$", None, "中：府號王爺合併為「X府千歲」"),
]

# 標記神明 → 原鄉（草稿）。「專案說明」列出的五尊標「說明已列」，其餘為候選、需查證。
# 祖籍不等於族群或語言，此表只記地名，不記族群。
MARKER_DEITIES = {
    "保生大帝": ("泉州府同安縣", "說明已列"),
    "清水祖師": ("泉州府安溪縣", "說明已列"),
    "開漳聖王": ("漳州府", "說明已列"),
    "三山國王": ("潮州府（粵東）", "說明已列"),
    "廣澤尊王": ("泉州府南安縣", "說明已列"),
    "法主公": ("泉州府安溪縣", "候選，待查證"),
    "保儀尊王": ("泉州府安溪縣", "候選，待查證"),
    "靈安尊王": ("泉州府惠安縣", "候選，待查證"),
    "定光古佛": ("汀州府", "候選，待查證"),
    "慚愧祖師": ("嘉應州／潮州府", "候選，待查證"),
}
SHARED_DEITIES = {"天上聖母", "福德正神", "觀世音菩薩"}  # 跨族群信仰，不納入原鄉分析
PREFIX = re.compile(r"^(南無|本師)+")
MULTI = re.compile(r"[、，,/／及與暨\s]")


def normalize(raw):
    if pd.isna(raw):
        return None, "缺值"
    name = PREFIX.sub("", raw.strip())
    for pattern, canonical, confidence in DEITY_RULES:
        m = re.search(pattern, name)
        if m:
            if canonical is None:
                return f"{m.group(1)}府千歲", confidence
            return canonical, confidence
    return name, "未比對：維持原寫法"


def parse_district(addr, county):
    """從地址取鄉鎮市區（行政區欄只到縣市）。"""
    if pd.isna(addr):
        return None
    rest = addr[len(county):] if addr.startswith(county) else addr
    m = re.match(r"^(.{1,4}?[區鄉鎮市])", rest)
    return m.group(1) if m else None


def haversine_km(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def main():
    REPORTS.mkdir(exist_ok=True)
    df = pd.read_csv(RAW / "temple_raw.csv", dtype=str)
    df["X"] = pd.to_numeric(df["WGS84X"], errors="coerce")
    df["Y"] = pd.to_numeric(df["WGS84Y"], errors="coerce")
    df["鄉鎮市區"] = [parse_district(a, c) for a, c in zip(df["地址"], df["行政區"])]
    md = []

    # 1. 欄位與缺值
    missing = pd.DataFrame({
        "欄位": df.columns[:-3],
        "缺值數": df[df.columns[:-3]].isna().sum().values,
    })
    missing["缺值比例"] = (missing["缺值數"] / len(df)).round(4)
    missing.to_csv(REPORTS / "fields_missing.csv", index=False, encoding="utf-8-sig")
    bad_coord = df["X"].notna() & ((df["X"] < 118) | (df["X"] > 122.5) | (df["Y"] < 21.5) | (df["Y"] > 26.5))
    md += ["## 1. 欄位與缺值", "", missing.to_markdown(index=False), "",
           f"- 座標落在台灣範圍外：{bad_coord.sum()} 筆（其中 X=0 有 {(df['X'] == 0).sum()} 筆）",
           f"- 地址無法解析出鄉鎮市區：{df['鄉鎮市區'].isna().sum()} 筆", ""]

    # 2. 筆數
    county = df["行政區"].value_counts().rename_axis("縣市").reset_index(name="筆數")
    county["有座標"] = county["縣市"].map(df[df["X"].notna() & ~bad_coord].groupby("行政區").size()).fillna(0).astype(int)
    county.to_csv(REPORTS / "counts_by_county.csv", index=False, encoding="utf-8-sig")
    tp = df[df["行政區"].isin(TAIPEI)]
    md += ["## 2. 筆數", "", f"- 全台：**{len(df):,}** 筆", *[
        f"- {c}：**{(df['行政區'] == c).sum():,}** 筆" for c in TAIPEI],
        f"- 台北市＋新北市合計：**{len(tp):,}** 筆，缺座標 {tp['X'].isna().sum()} 筆", "",
        county.to_markdown(index=False), ""]

    # 3. 主祀神祇
    vc = df["主祀神祇"].value_counts(dropna=False).rename_axis("主祀神祇").reset_index(name="次數")
    vc["主祀神祇"] = vc["主祀神祇"].fillna("（缺值）")
    vc.head(100).to_csv(REPORTS / "deity_spellings_top100.csv", index=False, encoding="utf-8-sig")
    vc_all = df["主祀神祇"].value_counts().rename_axis("原始寫法").reset_index(name="次數")
    norm = vc_all["原始寫法"].map(normalize)
    vc_all["正規名稱_草稿"] = [n for n, _ in norm]
    vc_all["比對信心"] = [c for _, c in norm]
    vc_all["疑似多神並列"] = vc_all["原始寫法"].str.contains(MULTI)
    vc_all["原鄉_草稿"] = vc_all["正規名稱_草稿"].map(lambda n: MARKER_DEITIES.get(n, ("", ""))[0])
    vc_all["原鄉依據"] = vc_all["正規名稱_草稿"].map(lambda n: MARKER_DEITIES.get(n, ("", ""))[1])
    vc_all.loc[vc_all["正規名稱_草稿"].isin(SHARED_DEITIES), "原鄉依據"] = "跨族群信仰，不納入"
    vc_all["審核結果"] = ""
    vc_all["審核備註"] = ""
    vc_all.to_csv(REPORTS / "deity_normalization_draft.csv", index=False, encoding="utf-8-sig")

    df["主神_草稿"] = df["主祀神祇"].map(lambda r: normalize(r)[0])
    canon = df["主神_草稿"].value_counts()
    covered = vc_all.head(100)["次數"].sum() / df["主祀神祇"].notna().sum()
    matched = vc_all[~vc_all["比對信心"].str.startswith("未比對")]["次數"].sum() / df["主祀神祇"].notna().sum()
    marker = df[df["主神_草稿"].isin(MARKER_DEITIES)]
    marker_tp = marker[marker["行政區"].isin(TAIPEI)]
    md += ["## 3. 主祀神祇寫法", "",
           f"- 不同寫法：**{len(vc_all):,}** 種；缺值 {df['主祀神祇'].isna().sum()} 筆",
           f"- 前 100 種寫法涵蓋 {covered:.1%} 的資料；規則比對涵蓋 {matched:.1%}",
           f"- 正規化後名稱數：{len(canon):,}；疑似多神並列寫法 {vc_all['疑似多神並列'].sum()} 種",
           f"- 標記神明（含候選）全台 {len(marker):,} 筆，台北市＋新北市 {len(marker_tp):,} 筆", "",
           "正規化後前 25 名：", "", canon.head(25).rename_axis("正規名稱").reset_index(name="筆數").to_markdown(index=False), "",
           "台北市＋新北市的標記神明：", "",
           marker_tp["主神_草稿"].value_counts().rename_axis("正規名稱").reset_index(name="筆數").to_markdown(index=False), ""]

    # 4. 台北盆地地址與座標
    tp = df[df["行政區"].isin(TAIPEI)].copy()
    addr = tp["地址"]
    fmt = {
        "以縣市開頭": addr.str.match(r"^(臺北市|新北市)").mean(),
        "含「號」": addr.str.contains("號").mean(),
        "含「路／街」": addr.str.contains("路|街").mean(),
        "含「鄰」": addr.str.contains("鄰").mean(),
        "含「之」號": addr.str.contains(r"\d+之\d+號|號之\d+").mean(),
        "含括號註記（暫厝等）": addr.str.contains(r"[（(]").mean(),
        "含「臨」號": addr.str.contains("臨").mean(),
        "無門牌（巷口、巷底等）": (~addr.str.contains("號")).mean(),
        "含樓層": addr.str.contains(r"\d+樓").mean(),
        "含全形數字": addr.str.contains(r"[０-９]").mean(),
        "連字號門牌（如 89-1號）": addr.str.contains(r"\d+-\d+號").mean(),
    }
    med = tp.groupby("鄉鎮市區")[["X", "Y"]].median()
    tp["距鄉鎮中位數_km"] = haversine_km(tp["X"], tp["Y"], tp["鄉鎮市區"].map(med["X"]), tp["鄉鎮市區"].map(med["Y"])).round(2)
    # 點離哪個鄉鎮中位數最近；與地址鄉鎮不符者為粗略可疑（不等於錯，邊界附近也會發生）
    d = np.stack([haversine_km(tp["X"].values, tp["Y"].values, mx, my) for mx, my in med.values], axis=1)
    nearest = np.where(np.isnan(d).all(axis=1), None, med.index.values[np.nan_to_num(d, nan=1e9).argmin(axis=1)])
    tp["最近鄉鎮中位數"] = nearest
    key = tp["X"].round(5).astype(str) + "," + tp["Y"].round(5).astype(str)
    tp["同座標筆數"] = key.map(key.value_counts())
    tp["旗標"] = ""
    tp.loc[tp["X"].isna(), "旗標"] += "缺座標;"
    tp.loc[tp["距鄉鎮中位數_km"] > 10, "旗標"] += "離所屬鄉鎮中心>10km;"
    tp.loc[tp["X"].notna() & (tp["最近鄉鎮中位數"] != tp["鄉鎮市區"]) & (tp["距鄉鎮中位數_km"] > 3), "旗標"] += "較靠近其他鄉鎮;"
    tp.loc[tp["X"].notna() & (tp["同座標筆數"] > 1), "旗標"] += "與他廟同座標;"
    cols = ["編號", "寺廟名稱", "主祀神祇", "地址", "鄉鎮市區", "X", "Y", "距鄉鎮中位數_km", "最近鄉鎮中位數", "同座標筆數", "旗標"]
    tp[tp["旗標"] != ""][cols].to_csv(REPORTS / "coord_flags_taipei.csv", index=False, encoding="utf-8-sig")
    sample = tp.sample(20, random_state=SEED)[cols]
    sample.to_csv(REPORTS / "taipei_address_sample.csv", index=False, encoding="utf-8-sig")
    flag_counts = {f: tp["旗標"].str.contains(f).sum() for f in ["缺座標", "離所屬鄉鎮中心>10km", "較靠近其他鄉鎮", "與他廟同座標"]}
    decimals = tp["WGS84X"].dropna().str.split(".").str[1].str.len()
    md += ["## 4. 台北市＋新北市地址與座標", "",
           "地址格式：", "", *[f"- {k}：{v:.1%}" for k, v in fmt.items()], "",
           f"- 鄉鎮市區數：{tp['鄉鎮市區'].nunique()}",
           f"- 座標小數位數中位數：{decimals.median():.0f}（像 float32 轉出的位數，不代表實際精度）",
           "座標粗略檢查（以鄉鎮中位數比對，非邊界多邊形；僅供篩出待人工確認的點）：", "",
           *[f"- {k}：{v} 筆" for k, v in flag_counts.items()], "",
           "抽樣 20 筆（random_state=8203）：", "", sample.to_markdown(index=False), ""]

    # 5. 其他欄
    other = df["其他"].dropna()
    years = other[other.str.contains(r"\d{3,4}|民國|年")]
    md += ["## 5. 「其他」欄", "", f"- 非空值：{len(other)} 筆；含年份樣式：{len(years)} 筆", ""]

    (REPORTS / "health_check.md").write_text(
        "# #8203 寺廟資料體檢（自動產生）\n\n" + "\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
