"""主祀神祇正規化規則與標記神明原鄉表（03 體檢、05 清理共用）。

審核原則（2026-11-03，Claude 依常見台灣民間信仰文獻說法審核，非田野確認）：
- 多神並列時，以第一尊為主神，其餘記為同祀。
- 「X府元帥」不併入王爺（田府元帥、謝府元帥、岳府元帥等是不同系統的神）。
- 不確定的合併標「低」信心；原鄉分析只採用信心為「高」的對應。
- 祖籍不等於族群或語言，原鄉欄只記地名。
"""
import re

import pandas as pd

# (正則, 正規名稱, 信心)。對「單一神名」比對，依序取第一個命中者。
DEITY_RULES = [
    (r"福德|土地公|土地爺|土地伯公|伯公", "福德正神", "高"),
    (r"天上聖母|媽祖|媽袓|天后|天妃|湄[洲州]聖母", "天上聖母", "高"),
    (r"釋迦|牟尼|摩尼", "釋迦牟尼佛", "高"),
    (r"觀世音|觀音|千手千眼", "觀世音菩薩", "高"),
    (r"玄天|真武|上帝公|北極(玄天|真武|上帝|大帝)", "玄天上帝", "高"),
    (r"關聖|關帝|關公|關夫子|文衡|協天|恩主公", "關聖帝君", "高"),
    (r"保生大帝|大道公|吳真人", "保生大帝", "高"),
    (r"清水祖師|蓬萊祖師|清水巖", "清水祖師", "高"),
    (r"^祖師公$|^祖師爺$", "清水祖師", "低"),
    (r"開漳聖王|陳聖王", "開漳聖王", "高"),
    (r"^聖王公$", "開漳聖王", "低"),
    (r"三山國王", "三山國王", "高"),
    (r"廣澤尊王|郭聖王", "廣澤尊王", "高"),
    (r"開[台臺]聖王|開台國[姓聖]|鄭成功|延平|國姓", "延平郡王", "高"),
    (r"中壇|太子爺|三太子|哪吒|那吒|太子元帥", "中壇元帥", "高"),
    (r"瑤池|西王金母|王母娘娘|金母", "瑤池金母", "高"),
    (r"玉皇(大帝|上帝|大天尊|大天至尊)|^玉皇$|^天公$", "玉皇大帝", "高"),
    (r"霞海城隍", "霞海城隍", "高"),
    (r"安溪.?城隍|清溪", "安溪城隍", "高"),
    (r"城隍", "城隍爺", "高"),
    (r"濟公|濟顛", "濟公活佛", "高"),
    (r"彌勒", "彌勒佛", "高"),
    (r"地藏", "地藏王菩薩", "高"),
    (r"神農|五[谷穀榖]", "神農大帝", "高"),
    (r"三官|三界公", "三官大帝", "高"),
    (r"孚佑|呂洞賓|純陽|呂祖", "孚佑帝君", "高"),
    (r"文昌", "文昌帝君", "高"),
    (r"張公聖君|張公法主|法主公|法主聖君", "法主公", "高"),
    (r"法主", "法主公", "低"),
    (r"保儀|尪公", "保儀尊王", "高"),
    (r"靈安尊王|青山王", "靈安尊王", "高"),
    (r"定光", "定光古佛", "高"),
    (r"慚愧祖師|陰那", "慚愧祖師", "高"),
    (r"萬應|萬善|有應公|百姓公|百姓媽|大眾爺|大墓公|金斗|聖公媽|萬姓公", "有應公類", "中"),
    (r"義民", "義民爺", "高"),
    (r"張天師|張府天師|廣信天師", "張天師", "高"),
    (r"田都元帥|田府元帥", "田都元帥", "高"),
]
FU_WANGYE = re.compile(r"^(.)府(千歲|王爺)$")  # 府號王爺合併為「X府千歲」
EXCLUDE = [(re.compile(r"陳淵"), "關聖帝君")]   # 「恩主公-陳淵」不是關公

# 標記神明 → 原鄉。層級：核心＝專案說明列出；延伸＝文獻常見說法，建議另外呈現。
MARKER_DEITIES = {
    "保生大帝": ("泉州府同安縣", "核心", "白礁慈濟宮祖廟；同安移民主要信仰"),
    "清水祖師": ("泉州府安溪縣", "核心", "安溪清水巖祖廟"),
    "開漳聖王": ("漳州府", "核心", "陳元光，漳州開發者"),
    "三山國王": ("潮州府（粵東）", "核心", "揭陽三山；不等同客家"),
    "廣澤尊王": ("泉州府南安縣", "核心", "南安鳳山寺祖廟"),
    "霞海城隍": ("泉州府同安縣", "延伸", "同安霞城城隍；大稻埕霞海城隍廟由同安人奉祀"),
    "安溪城隍": ("泉州府安溪縣", "延伸", "安溪清溪城隍"),
    "靈安尊王": ("泉州府惠安縣", "延伸", "惠安青山宮；艋舺青山宮由惠安人奉祀"),
    "保儀尊王": ("泉州府安溪縣", "延伸", "台北木柵、景美集應廟由安溪高、張、林姓奉祀"),
    "定光古佛": ("汀州府", "延伸", "汀州武平；淡水鄞山寺由汀州人奉祀"),
    "慚愧祖師": ("嘉應州", "延伸", "陰那山；中部山區較多"),
}
# 法主公的祖廟在永泰（福州府），與台北安溪茶商的連結屬於後來的發展，不列入原鄉，避免誤導。
SHARED_DEITIES = {"天上聖母", "福德正神", "觀世音菩薩"}

PREFIX = re.compile(r"^(南無|本師|無極)+")
PAREN = re.compile(r"[（(〈<].*?[）)〉>]")
SPLIT = re.compile(r"[、，,/／;；.．\s\-]+|及|暨")


def _match(token):
    for pattern, canonical, confidence in DEITY_RULES:
        if re.search(pattern, token):
            return canonical, confidence
    m = FU_WANGYE.match(token)
    if m:
        return f"{m.group(1)}府千歲", "高"
    return None, None


def normalize(raw):
    """回傳 dict：主神、信心、同祀、是否多神。"""
    if raw is None or pd.isna(raw) or not str(raw).strip():
        return {"主神": None, "主神_信心": "缺值", "同祀": "", "多神並列": False}
    text = str(raw).strip()
    alias = " ".join(PAREN.findall(text))
    tokens = [PREFIX.sub("", t) for t in SPLIT.split(PAREN.sub("", text)) if t.strip()]
    tokens = tokens or [text]
    results = []
    for t in tokens:
        canonical, confidence = _match(t)
        if canonical is None and t == tokens[0] and alias:
            canonical, confidence = _match(alias)
        results.append((canonical or t, confidence or "未比對"))
    main, conf = results[0]
    for pat, blocked in EXCLUDE:
        if main == blocked and pat.search(text):
            main, conf = tokens[0], "未比對"
    others = [c for c, _ in results[1:] if c != main]
    return {"主神": main, "主神_信心": conf, "同祀": "、".join(dict.fromkeys(others)),
            "多神並列": len(tokens) > 1}


def hometown(canonical, confidence):
    """回傳 (原鄉, 層級, 依據)。只有高信心的對應才給原鄉。"""
    if canonical in SHARED_DEITIES:
        return "", "跨族群信仰", ""
    if canonical in MARKER_DEITIES:
        place, tier, note = MARKER_DEITIES[canonical]
        if confidence != "高":
            return "", "信心不足不採用", note
        return place, tier, note
    return "", "", ""
