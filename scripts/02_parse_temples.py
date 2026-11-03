"""把 data/raw/temple.xml 解析成 CSV。

- data/raw/temple_raw.csv：所有欄位原樣（含電話、負責人；僅供內部，不發布）
- data/processed/temples.csv：去除個資欄位（電話、負責人），座標轉數值
"""
from pathlib import Path
import xml.etree.ElementTree as ET

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
PII_COLUMNS = ["電話", "負責人"]


def parse(xml_path):
    rows, columns = [], []
    for rec in ET.parse(xml_path).getroot():
        row = {}
        for el in rec:
            if el.tag not in columns:
                columns.append(el.tag)
            text = (el.text or "").strip()
            row[el.tag] = text if text else None
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def main():
    df = parse(RAW / "temple.xml")
    df.to_csv(RAW / "temple_raw.csv", index=False, encoding="utf-8-sig")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    out = df.drop(columns=[c for c in PII_COLUMNS if c in df.columns])
    for c in ("WGS84X", "WGS84Y"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out.to_csv(PROCESSED / "temples.csv", index=False, encoding="utf-8-sig")
    print(f"{len(df)} rows, columns: {list(df.columns)}")


if __name__ == "__main__":
    main()
