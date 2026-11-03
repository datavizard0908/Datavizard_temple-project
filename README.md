# Datavizard Temple Project

> 專案簡介：**神明住在哪裡？** 以台灣寺廟開放資料製作的互動式資料視覺化網站（課程專案，非商業用途），用資料說「信仰、移民、城市」的故事：今天廟裡拜的神，還記得一百年前住在這裡的人從哪裡來嗎？

## 團隊成員

| 成員 | GitHub 帳號 | 負責項目 |
| --- | --- | --- |
| （名字） | @（帳號） | （待補充） |
| （名字） | @（帳號） | （待補充） |
| （名字） | @（帳號） | （待補充） |

## 開始使用

```bash
git clone https://github.com/datavizard0908/Datavizard_temple-project.git
cd Datavizard_temple-project
```

第一次使用前，請設定自己的 git 名字與信箱，讓 commit 看得出是誰改的：

```bash
git config --global user.name "你的名字"
git config --global user.email "你的GitHub信箱"
```

## 協作流程

1. 開始工作前先拉最新版：`git pull`
2. 開一個自己的分支，不要直接改 `main`：
   `git switch -c feature/功能名稱`
3. 寫完後 commit 並推上 GitHub：
   `git push -u origin feature/功能名稱`
4. 在 GitHub 開 Pull Request，請另一位成員看過再合併進 `main`
5. 合併後切回 `main` 並更新：`git switch main && git pull`

### 分支命名

- `feature/…`：新功能
- `fix/…`：修 bug
- `docs/…`：文件修改

## 專案結構

```
data/
  raw/          原始資料（不進 repo，由腳本重新下載；含個資）
  processed/    清理後資料（已移除電話、負責人）
  reference/    審核後的對照表（主神正規化、原鄉）
scripts/        資料處理腳本，依編號順序執行
reports/        資料體檢報告，先看 reports/SUMMARY.md
site/           網站（目前是資料預覽頁）
```

### 重跑資料流程

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS／Linux：.venv/bin/pip
```

1. `scripts/01_fetch_temples.py`：下載 data.gov.tw #8203 寺廟 XML（需要 curl）
2. `scripts/02_parse_temples.py`：XML → CSV，移除個資欄位
3. `scripts/03_health_check.py`：體檢報告（缺值、筆數、主神寫法、地址抽樣）
4. `scripts/04_check_coords.py`：座標落區檢查。需先把國土測繪中心鄉鎮界（#7441）的 `TOWN_MOI_*` 解壓到 `data/raw/town_boundary/`
5. `scripts/05_geocode_fix.py`：用 OSM Nominatim 補有問題的座標（每秒 1 次，有快取，全量約 30–40 分鐘）
6. `scripts/06_build_clean.py`：產生分析用資料與網站資料。需先把村里界（#7438）的 `VILLAGE_NLSC_*` 解壓到 `data/raw/village_boundary/`

### 看預覽頁

```bash
python -m http.server 8765 --directory site
```

然後開 http://localhost:8765

### 資料來源與授權

- 寺廟：內政部〈全國宗教資訊系統資料－寺廟〉（data.gov.tw #8203），政府資料開放授權條款第 1 版
- 鄉鎮界、村里界：國土測繪中心（#7441、#7438），政府資料開放授權條款第 1 版
- 部分補點座標：© OpenStreetMap 貢獻者，ODbL（`coord_source` 為 `nominatim_*` 的列）
- 底圖：OpenFreeMap © OpenMapTiles © OpenStreetMap 貢獻者
