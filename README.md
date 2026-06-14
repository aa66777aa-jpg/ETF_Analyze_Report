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
| **價格 vs MA60 偏差** | 低於 MA60 超過 5%（+1 分，且均線向上） | 高於 MA60 超過 8%（-1 分） |
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
- HTML 報告由 `report_template.html` 與 `report.css` 作為模板自動生成，可自行修改樣式

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

> 本專案透過 `curl-cffi` 改善 Yahoo Finance 下載的穩定性，`uv sync` 會自動安裝，無需額外設定。

## 使用方式

### 執行分析

```bash
uv run python main.py
```

> 不需要先 activate 虛擬環境，`uv run` 會自動使用 `.venv`。

### 新增套件

```bash
uv add <套件名>
```

### 使用 Makefile（含 lint & format）

```bash
make help   # 顯示可用的 Makefile 指令
make lint   # ruff 檢查、格式化並清除 cache
make run    # 執行 main.py（透過 uv 自動安裝相依套件）
make all    # update → lint → run
make update # 更新 uv 本身
```

## 設定

開啟 [main.py](main.py) 修改以下參數：

```python
# 要觀察的股票清單（Yahoo Finance 代號）
STOCK_LIST = [
    "009816.TW",    # 凱基台灣TOP50
    "00685L.TW",    # 群益臺灣加權正2
    "EWY",          # iShares MSCI 南韓 ETF（美股）
    "^TWII",        # 加權指數（市場環境參考）
    "^GSPC",        # S&P 500（市場環境參考）
    "^IXIC",        # 那斯達克（市場環境參考）
    "^KS11",        # 韓國 KOSPI 指數（市場環境參考）
    # 繼續新增你想觀察的股票代號...
]

LOOKBACK_DAYS = 365   # 顯示的觀察天數
WARMUP_DAYS = 180     # 指標暖機天數（建議不低於 180，確保 MA120 計算正確）
RSI_PERIOD = 14       # RSI 回看天數
W_PERIOD = 14         # Williams %R 回看天數
MA_PERIODS = (20, 60, 120)  # 移動均線參數
HIGH_WINDOW = 252     # 52 週高點視窗（約 1 年交易日）
MIN_TRADING_DAYS = 120  # 觀察區間最少交易日（不足則自動跳過該股票）
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

## 指標邏輯說明

### RSI（相對強弱指數）

採用 **Wilder's Smoothing**（指數移動平均，alpha = 1/14）計算，與多數交易軟體一致。

- RSI < 35 → 超賣，代表近期跌幅相對大，回彈機率提升 → **+1 分**
- RSI > 70 → 過熱，代表近期漲幅相對大，短期風險偏高 → **-1 分**

### 距 52 週高點跌幅（Drawdown from 52W High）

以過去 `HIGH_WINDOW`（預設 252）個交易日的最高收盤價為基準，計算當前收盤的相對跌幅。

- 跌幅 ≤ -15% → 明顯回落，逢低加碼機會 → **+2 分**
- -15% < 跌幅 ≤ -8% → 有所回落 → **+1 分**
- 跌幅 ≥ -3% → 接近歷史高點，較貴 → **-1 分**

> 若該股票上市未滿 `HIGH_WINDOW` 個交易日，信號欄位會加註「高點視窗僅 N 日」提示。

### 價格 vs MA60 偏差（含均線方向過濾）

計算收盤價相對 60 日移動平均的百分比偏差，並加入**均線斜率過濾**：

- 低於 MA60 超過 5% 且 **均線向上**（近 20 日斜率為正）→ 回檔加碼機會 → **+1 分**
- 低於 MA60 超過 5% 但 **均線下彎** → 下跌趨勢，降為 **0 分（謹慎觀察）**
- 高於 MA60 超過 8% → 過度延伸，短期風險 → **-1 分**

### Williams %R

以過去 `W_PERIOD`（預設 14）個交易日的最高價與最低價計算：

```
W%R = (最高價 - 收盤) / (最高價 - 最低價) × (-100)
```

- W%R ≤ -80 → 超賣區 → **+1 分**
- W%R ≥ -20 → 超買區 → **-1 分**

> 當近 14 日價格波動極小（區間小於收盤價 0.3%），視為橫盤，W%R 設為 NaN 並計為中性（0 分）。

### 指數市場環境判斷

代號以 `^` 開頭的指數不輸出加碼建議，改用多空計票判斷整體市場環境：

| 環境 | 條件（四項中達到幾項） |
|------|----------------------|
| **偏多** | ≥ 3 項多頭訊號（RSI > 60、接近高點、MA60 偏差 > 3%、W%R ≥ -20） |
| **偏空** | ≥ 3 項空頭訊號（RSI < 45、距高點回落 > 8%、MA60 偏差 < -3%、W%R ≤ -80） |
| **中性** | 其餘情況 |

## 專案架構

```
ETF_Analyze_Report/
├── main.py                  # 主程式：下載資料、計算指標、繪圖、生成報告
├── report_template.html     # HTML 報告模板（%%佔位符%%由程式替換）
├── report.css               # 報告樣式表（執行時自動內嵌至 docs/index.html）
├── Makefile                 # 常用指令：lint / run / all / update
├── pyproject.toml           # uv 專案設定與依賴宣告
├── uv.lock                  # 鎖定的依賴版本（確保環境一致）
├── Report/                  # 輸出的 PNG 圖檔（每支股票一張）
├── docs/
│   └── index.html           # 自包含 HTML 報告（base64 內嵌圖片，用於 GitHub Pages）
└── .github/
    └── workflows/
        └── daily-etf.yml    # GitHub Actions 自動排程
```

## 自動排程

GitHub Actions 每個交易日自動執行兩次，結果自動 commit 至 repo 並更新 GitHub Pages：

- **台股收盤後**：台灣時間週一至週五 14:30（UTC 06:30）
- **美股收盤後**：台灣時間週二至週六 06:30（UTC 22:30，冬夏令皆安全）

### GitHub Actions 執行流程

```
Checkout repo
  → 安裝中文字體（Noto CJK / WenQuanYi）
  → 安裝 uv 並執行 uv sync
  → 清除 matplotlib 字體快取
  → uv run python main.py
  → git add Report/*.png docs/index.html
  → git commit & push
```

手動觸發：GitHub repo → Actions → Daily ETF Analysis → **Run workflow**

## 依賴套件

| 套件 | 版本 | 用途 |
|------|------|------|
| `yfinance` | ≥ 0.2.54 | Yahoo Finance 股價下載 |
| `pandas` | ≥ 2.0.0 | 資料處理與時間序列計算 |
| `matplotlib` | ≥ 3.8.0 | 圖表繪製 |
| `curl-cffi` | ≥ 0.7 | 改善 Yahoo Finance 連線穩定性 |

## 常見問題

**Q：執行時出現 `⚠️ xxx 無資料，跳過` 是什麼原因？**

A：可能原因：(1) 股票代號拼錯、(2) Yahoo Finance 暫時無法連線、(3) 該股票已下市或停牌。確認代號格式後重試。

**Q：為什麼某支股票的 Williams %R 顯示「橫盤無法計算」？**

A：當近 14 個交易日的最高價與最低價差距小於收盤價的 0.3% 時，視為極度橫盤，W%R 分母趨近於零，結果無意義，程式自動設為 NaN 並計為中性。

**Q：為什麼 MA60 低於 5% 但建議顯示「謹慎觀察」而非「加碼」？**

A：程式加入了均線斜率過濾：若 MA60 在近 20 個交易日呈現下彎（斜率為負），即使價格跌破 MA60，也視為下跌趨勢中的回踩，不給加碼訊號。

**Q：GitHub Actions 執行失敗怎麼辦？**

A：到 Actions 頁面查看錯誤日誌。常見原因：Yahoo Finance 暫時封鎖 GitHub IP（重新手動觸發通常可解決）、`pyproject.toml` 依賴版本衝突。

**Q：如何停止 GitHub Actions 自動執行？**

A：GitHub repo → Actions → Daily ETF Analysis → 右上角 `...` → **Disable workflow**。

## 免責聲明

> 本工具輸出的所有內容（包含圖表、評分、建議標籤）**僅供個人學習與參考，不構成任何形式的投資建議**。
>
> 四項技術指標（RSI、距高點跌幅、MA60 偏差、Williams %R）均屬均值回歸類指標，彼此相關性高，綜合評分僅反映短期技術面狀態，無法預測未來走勢。
>
> 投資前請自行評估風險，並諮詢專業財務顧問。
