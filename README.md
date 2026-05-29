# ETF 技術指標分析工具

自動從 Yahoo Finance 下載股價資料，計算多種技術指標，並輸出圖表與 HTML 報告。

## 線上報告

GitHub Pages 報告：

> **https://&lt;your-username&gt;.github.io/&lt;repo-name&gt;/**

> 啟用方式：GitHub repo → Settings → Pages → Source 選 `Deploy from a branch`，Branch 選 `main`，Folder 選 `/docs`

## 功能

- **威廉指標（Williams %R）**：識別超買（> -20）與超賣（< -80）區間
- **多空指標（BBI）**：3、6、12、24 日均線平均，判斷趨勢方向
- **MACD**：DIF / DEA 雙線與 OSC 柱狀圖
- **成交量分析**：MA5 / MA20 均量線，並標記爆量日（量比 ≥ 2）
- 每支股票輸出一張四格子技術圖，標示期間報酬率

## 輸出

- PNG 圖檔存於 `Report/` 資料夾
- 自包含 HTML 報告存於 `docs/index.html`（圖片以 base64 內嵌，單一檔案即可離線查看）

## 安裝

```bash
pip install -r requirements.txt
```

或使用 `uv`：

```bash
uv pip install -r requirements.txt
```

**需求版本：**

| 套件 | 版本 |
|---|---|
| yfinance | ≥ 0.2.54 |
| pandas | ≥ 2.0.0 |
| matplotlib | ≥ 3.8.0 |

## 使用方式

### 直接執行

```bash
python ETF.py
```

### 使用 Makefile（含 lint & format）

```bash
make lint   # ruff 檢查並格式化
make run    # 執行 ETF.py（透過 uv 自動安裝相依套件）
make all    # lint 後接著 run
```

## 設定

開啟 [ETF.py](ETF.py) 修改以下參數：

```python
# 要觀察的股票清單（Yahoo Finance 代號）
STOCK_LIST = [
    "009816.TW",   # 台股 ETF
    "00935.TW",
    "^TWII",        # 加權指數
    "^DJI",         # 道瓊
    "^GSPC",        # S&P 500
    "^IXIC",        # 那斯達克
]

LOOKBACK_DAYS = 365   # 觀察天數
WARMUP_DAYS = 60      # 多空指標回看天數
W_PERIOD = 14         # 威廉指標回看天數
```

股票代號格式參考 Yahoo Finance：
- 台股 ETF：`00935.TW`
- 台股個股：`2330.TW`
- 美股指數：`^DJI`、`^GSPC`、`^IXIC`
- 美股個股：`AAPL`、`TSLA`

## 圖表內容

每支股票產生一個四格子技術圖，圖表包含：

1. 收盤價（還原）+ BBI 線，標示期間報酬率
2. Williams %R，標示超買 / 超賣水平線
3. MACD（DIF、DEA、OSC 柱狀圖）
4. 成交量（MA5、MA20，爆量日標紅點）
