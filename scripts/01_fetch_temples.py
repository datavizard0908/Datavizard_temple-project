"""下載 data.gov.tw #8203（全國宗教資訊系統資料-寺廟）原始 XML。

真實下載網址從 data.gov.tw metadata API 取得（不寫死），
原始檔存 data/raw/，並記錄抓取時間與 metadata 供來源標示。

檔案本體用 curl 下載：religion.moi.gov.tw 的憑證缺 Subject Key Identifier，
Python 3.13+ 的嚴格 X.509 檢查會拒絕；curl（Windows 上走 Schannel）可正常驗證。
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

DATASET_ID = 8203
UA = "TempleProject/0.1 (course project; data health check)"
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    meta = requests.get(
        f"https://data.gov.tw/api/v2/rest/dataset/{DATASET_ID}",
        headers={"User-Agent": UA},
        timeout=60,
    ).json()["result"]
    url = meta["distribution"][0]["resourceDownloadUrl"]

    out = RAW / "temple.xml"
    subprocess.run(["curl", "-sS", "-f", "-A", UA, "-o", str(out), url], check=True)

    fetched = {
        "dataset_id": DATASET_ID,
        "title": meta["title"],
        "license": "政府資料開放授權條款－第1版" if meta.get("license") == "1" else meta.get("license"),
        "modified_date": meta.get("modifiedDate"),
        "download_url": url,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bytes": out.stat().st_size,
    }
    (RAW / "temple.fetch.json").write_text(
        json.dumps(fetched, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(fetched, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
