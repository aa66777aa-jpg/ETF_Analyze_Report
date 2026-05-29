# ETF 定期投入時機分析工具

自動從 Yahoo Finance 下載股價資料，根據四項技術指標判斷 **現在是否適合加碼**，輸出圖表與 HTML 報告。

## 線上報告

GitHub Pages 報告：

> **https://&lt;your-username&gt;.github.io/&lt;repo-name&gt;/**

> 啟用方式：GitHub repo → Settings → Pages → Source 選 `Deploy from a branch`，Branch 選 `main`，Folder 選 `/docs`

## 功能

針對 **ETF 定期投入逢低加碼** 的判斷需求，分析四項指標：

| 指標 | 加碼訊號 | 暫緩訊號 |
|------|---------|---------|
| **RSI（14日）** | RSI < 35（超賣） | RSI > 70（過熱） |
| **距 52 週高點跌幅** | 跌幅 > 8% | 距高點 < 3%（接近高點） |
| **價格 vs MA60 偏差** | 低於 MA60 超過 5% | 高於 MA60 超過 8% |
| **Williams %R（14日）** | %R ≤ -80（超賣） | %R ≥ -20（超買） |

**綜合評分（-4 ~ +4）：**

| 評分 | 建議 |
|------|------|
| +2 以上 | 積極加碼 |
| +1 | 考慮加碼 |
| 0 | 正常定期投入 |
| -1 | 謹慎觀察 |
| -2 以下 | 暫緩加碼 |

## 輸出

- PNG 圖檔存於 `Report/` 資料夾（四格圖：均線 / RSI / Williams %R / 距高點跌幅）
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
WARMUP_DAYS = 180     # 指標暖機天數（建議不低於 180，確保 MA120 計算正確）
RSI_PERIOD = 14       # RSI 回看天數
W_PERIOD = 14         # Williams %R 回看天數
```

股票代號格式參考 Yahoo Finance：
- 台股 ETF：`00935.TW`
- 台股個股：`2330.TW`
- 美股指數：`^DJI`、`^GSPC`、`^IXIC`
- 美股個股：`AAPL`、`TSLA`

## 圖表內容

每支股票產生一個四格子圖，包含：

1. **收盤價 + MA20 / MA60 / MA120**：觀察均線支撐位
2. **RSI**：超賣區（< 35）紅色底色，過熱區（> 70）綠色底色
3. **Williams %R**：超賣（≤ -80）與超買（≥ -20）區間標示
4. **距 52 週高點跌幅**：紅色填充 = 積極加碼區（> 15%），橙色 = 考慮加碼區（8~15%）

## 自動排程

GitHub Actions 每個交易日自動執行兩次（台股收盤後 / 美股收盤後），結果自動 commit 至 repo 並更新 GitHub Pages。
