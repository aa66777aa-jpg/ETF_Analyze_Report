# ETF 定期投入時機分析工具

自動從 Yahoo Finance 下載股價資料，根據四項技術指標判斷 **現在是否適合加碼**，輸出圖表與 HTML 報告。

## 線上報告

GitHub Pages 報告：

> **https://aa66777aa-jpg.github.io/ETF_Analyze_Report/**

> 啟用方式：GitHub repo → Settings → Pages → Source 選 `Deploy from a branch`，Branch 選 `main`，Folder 選 `/docs`

## 功能

針對 **ETF 定期投入逢低加碼** 的判斷需求，分析四項指標：

| 指標 | 加碼訊號 | 暫緩訊號 |
|------|---------|---------|
| **RSI（14日）** | RSI < 35（超賣）+1 分 | RSI > 70（過熱）-1 分 |
| **距 52 週高點跌幅** | 跌幅 > 15%（+2 分）/ 跌幅 > 8%（+1 分） | 距高點 < 3%（接近高點）-1 分 |
| **價格 vs MA60 偏差** | 低於 MA60 超過 5%（+1 分） | 高於 MA60 超過 8%（-1 分） |
| **Williams %R（14日）** | %R ≤ -80（超賣）+1 分 | %R ≥ -20（超買）-1 分 |

**綜合評分（-4 ~ +5）：**

| 評分 | 建議 |
|------|------|
| +2 以上 | 積極加碼 |
| +1 | 考慮加碼 |
| 0 | 正常定期投入 |
| -1 | 謹慎觀察 |
| -2 以下 | 暫緩加碼 |

> **指數（`^` 開頭）**不給買賣建議，改輸出市場環境標籤（偏多 / 中性 / 偏空），供研判整體背景參考。

## 輸出

- PNG 圖檔存於 `Report/` 資料夾（四格圖：均線+量比 / RSI / Williams %R / 距高點跌幅）
- 自包含 HTML 報告存於 `docs/index.html`（圖片以 base64 內嵌，單一檔案即可離線查看）

## 安裝

本專案使用 [uv](https://docs.astral.sh/uv/) 管理依賴，需要 **Python 3.13+**。

**安裝 uv（第一次才需要）：**

```powershell
# Windows
winget install astral-sh.uv
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**安裝專案依賴：**

```bash
uv sync
```

執行後會自動建立 `.venv` 並安裝所有套件，不需要手動 `pip install`。

## 使用方式

### 執行分析

```bash
uv run python ETF.py
```

> 不需要先 activate 虛擬環境，`uv run` 會自動使用 `.venv`。

### 新增套件

```bash
uv add <套件名>
```

### 使用 Makefile（含 lint & format）

```bash
make lint   # ruff 檢查、格式化並清除 cache
make run    # 執行 ETF.py（透過 uv 自動安裝相依套件）
make all    # lint 後接著 run
make update # 更新 uv 本身
```

## 設定

開啟 [ETF.py](ETF.py) 修改以下參數：

```python
# 要觀察的股票清單（Yahoo Finance 代號）
STOCK_LIST = [
    "009816.TW",    # 台股 ETF
    "00631L.TW",    # 台灣 50 正 2
    "^TWII",        # 加權指數（市場環境參考）
    "^GSPC",        # S&P 500（市場環境參考）
    "^IXIC",        # 那斯達克（市場環境參考）
    # 繼續新增你想觀察的股票代號...
]

LOOKBACK_DAYS = 365   # 顯示的觀察天數
WARMUP_DAYS = 180     # 指標暖機天數（建議不低於 180，確保 MA120 計算正確）
RSI_PERIOD = 14       # RSI 回看天數
W_PERIOD = 14         # Williams %R 回看天數
MA_PERIODS = (20, 60, 120)  # 移動均線參數
HIGH_WINDOW = 252     # 52 週高點視窗（約 1 年交易日）
```

股票代號格式參考 Yahoo Finance：
- 美股 ETF：`EWY`
- 台股個股：`2330.TW`
- 韓國指數：`^KS11`
- 美股指數：`^GSPC`、`^IXIC`
- 美股個股：`AAPL`、`TSLA`

## 圖表內容

每支股票產生一個四格子圖，包含：

1. **收盤價 + MA20 / MA60 / MA120 + 量比**：觀察均線支撐位，量比（相對 20 日均量）以彩色長條顯示於圖底
2. **RSI**：超賣區（< 35）紅色底色，過熱區（> 70）綠色底色
3. **Williams %R**：超賣（≤ -80）與超買（≥ -20）區間標示
4. **距 52 週高點跌幅**：紅色填充 = 積極加碼區（> 15%），橙色 = 考慮加碼區（8~15%）

## 自動排程

GitHub Actions 每個交易日自動執行兩次（台股收盤後 / 美股收盤後），結果自動 commit 至 repo 並更新 GitHub Pages。
