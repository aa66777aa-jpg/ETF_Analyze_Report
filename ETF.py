import base64
import os
from datetime import date, datetime, timedelta, timezone

import matplotlib
import matplotlib.font_manager as _fm
import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf

# 動態偵測系統上實際存在的 CJK 字體（解決 Ubuntu CI 的 TTC 解析不穩定問題）
_CJK_KEYWORDS = ("NotoSansCJK", "wqy", "WenQuanYi", "NotoSans")
for _fp in _fm.findSystemFonts():
    if any(k.lower() in _fp.lower() for k in _CJK_KEYWORDS):
        _fm.fontManager.addfont(_fp)

matplotlib.rcParams["font.family"] = [
    "Microsoft JhengHei",   # Windows 繁體中文（微軟正黑體）
    "Microsoft YaHei",      # Windows 簡體中文（微軟雅黑）
    "WenQuanYi Zen Hei",
    "WenQuanYi Micro Hei",
    "Noto Sans CJK TC",
    "Noto Sans TC",
    "Heiti TC",
    "Arial Unicode MS",
    "sans-serif",
]
matplotlib.rcParams["axes.unicode_minus"] = False

_BASE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_BASE, "Report")
DOCS_DIR = os.path.join(_BASE, "docs")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)

# ==========================================
# ✏️  在這裡設定要觀察的股票清單
# ==========================================
STOCK_LIST = [
    "009816.TW",
    "00935.TW",
    "^TWII",
    "^DJI",
    "^GSPC",
    "^IXIC",
    # 繼續新增你想觀察的股票代號...
]

LOOKBACK_DAYS = 365  # 觀察天數
WARMUP_DAYS = 60  # 多空指標回看天數
W_PERIOD = 14  # 威廉指標回看天數
BBI_PERIODS = (3, 6, 12, 24)  # BBI 均線參數
VOL_MA_SHORT = 5  # 短期量均
VOL_MA_LONG = 20  # 長期量均
TODAY = date.today().isoformat()
END_DATE = (date.today() + timedelta(days=1)).isoformat()  # yfinance end is exclusive
START_DATE = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
FETCH_START = (date.today() - timedelta(days=LOOKBACK_DAYS + WARMUP_DAYS)).isoformat()


def _safe_id(stock_id: str) -> str:
    return stock_id.replace("^", "").replace(".", "_")


def _price_col(df: pd.DataFrame) -> str:
    return "Adj Close" if "Adj Close" in df.columns else "Close"


def analyze_stock(stock_id: str):
    """下載並計算單支股票的技術指標，回傳 DataFrame；若資料不足則回傳 None。"""
    print(f"\n📥 正在下載：{stock_id} ...")
    df = yf.download(
        stock_id, start=FETCH_START, end=END_DATE, progress=False, auto_adjust=False
    )

    if df.empty:
        print(f"⚠️  {stock_id} 無資料，跳過。")
        return None

    # 清理欄位多重索引（新版 yfinance 有時會產生多重索引）
    # level 0 恆為 Price 名稱（Adj Close / Close / High…），直接取用
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # auto_adjust=False 時使用 Adj Close 計算指標，Volume 維持原始值對應 Yahoo Finance
    price = df[_price_col(df)]

    # --- 威廉指標 (Williams %R) ---
    high_n = df["High"].rolling(window=W_PERIOD).max()
    low_n = df["Low"].rolling(window=W_PERIOD).min()
    df["Williams_%R"] = ((high_n - price) / (high_n - low_n)) * -100

    # --- 多空指標 (BBI) ---
    df["BBI"] = sum(price.rolling(window=p).mean() for p in BBI_PERIODS) / len(
        BBI_PERIODS
    )

    # --- MACD ---
    ema12 = price.ewm(span=12, adjust=False).mean()
    ema26 = price.ewm(span=26, adjust=False).mean()
    df["MACD_DIF"] = ema12 - ema26
    df["MACD_DEA"] = df["MACD_DIF"].ewm(span=9, adjust=False).mean()
    df["MACD_OSC"] = df["MACD_DIF"] - df["MACD_DEA"]

    # --- 成交量分析 ---
    # 部分指數（如 ^DJI、^TWII）Yahoo Finance 回報 Volume 為 NaN 或 0，
    # 若不先填補，Vol_MA20=0 → Vol_Ratio=NaN/inf → dropna 會清空整個 df。
    df["Volume"] = df["Volume"].fillna(0)
    df["Vol_MA5"] = df["Volume"].rolling(window=VOL_MA_SHORT).mean()
    df["Vol_MA20"] = df["Volume"].rolling(window=VOL_MA_LONG).mean()
    df["Vol_Ratio"] = df["Volume"] / df["Vol_MA20"]  # 量比（相對長期均量）
    # 將除以 0 產生的 inf 轉為 NaN，再統一用 0 填補（量比無意義時視為 0）
    df["Vol_Ratio"] = (
        df["Vol_Ratio"]
        .replace([float("inf"), float("-inf")], float("nan"))
        .fillna(0)
    )

    # dropna 排除 Vol_Ratio（已手動填補），僅對其餘指標欄位做清理
    non_vol_cols = [c for c in df.columns if c != "Vol_Ratio"]
    df.dropna(subset=non_vol_cols, inplace=True)

    if df.empty:
        print(f"⚠️  {stock_id} dropna 後無資料，跳過。")
        return None

    # 截回真正的觀察區間（暖機資料已完成指標計算，不再需要）
    df = df[df.index >= pd.Timestamp(START_DATE)]

    if df.empty:
        print(f"⚠️  {stock_id} 截回觀察區間後無資料，跳過。")
        return None

    return df


def calc_period_return(df: pd.DataFrame) -> tuple[float, int]:
    """計算觀察期間總報酬率與實際天數（使用還原後價格）。"""
    col = _price_col(df)
    first_close = df[col].iloc[0]
    last_close = df[col].iloc[-1]
    n_days = (df.index[-1] - df.index[0]).days
    if n_days <= 0:
        return float("nan"), 0
    total_return = (last_close - first_close) / first_close
    return total_return, n_days


def plot_stock(stock_id: str, df: pd.DataFrame):
    """繪製單支股票的四格子圖並存檔。"""
    period_ret, n_days = calc_period_return(df)
    period_ret_str = (
        f"{period_ret * 100:+.2f}% ({n_days}天)" if not pd.isna(period_ret) else "N/A"
    )
    if pd.isna(period_ret):
        ann_ret_color = "#888888"
    elif period_ret >= 0:
        ann_ret_color = "#e63946"  # 台股慣例：漲紅跌綠
    else:
        ann_ret_color = "#2a9d8f"

    fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(13, 14), sharex=True)
    fig.suptitle(
        f"{stock_id}  技術指標分析  ({START_DATE} ~ {TODAY})",
        fontsize=14,
        fontweight="bold",
    )

    # ── 圖一：股價 & BBI ─────────────────────────────
    col = _price_col(df)
    ax1.plot(df.index, df[col], label="收盤價(還原)", color="black", linewidth=1.5)
    ax1.plot(df.index, df["BBI"], label="BBI", color="orange", linestyle="--")
    ax1.set_ylabel("Price")

    first_price = df[col].iloc[0]
    last_price = df[col].iloc[-1]
    ax1.annotate(
        f"期間報酬率：{period_ret_str}\n"
        f"期初：{first_price:.2f}  →  期末：{last_price:.2f}",
        xy=(df.index[-1], last_price),
        xytext=(-10, 10),
        textcoords="offset points",
        ha="right",
        fontsize=9,
        color=ann_ret_color,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=ann_ret_color, alpha=0.8),
    )

    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.4)

    # ── 圖二：威廉指標 ───────────────────────────────
    ax2.plot(
        df.index, df["Williams_%R"], label=f"Williams %R ({W_PERIOD})", color="purple"
    )
    ax2.axhline(-20, color="red", linestyle=":", linewidth=1, label="超買 (-20)")
    ax2.axhline(-80, color="green", linestyle=":", linewidth=1, label="超賣 (-80)")
    ax2.set_ylabel("Williams %R")
    ax2.set_ylim(-105, 5)
    ax2.legend(loc="upper left")
    ax2.grid(True, alpha=0.4)

    # ── 圖三：MACD ───────────────────────────────────
    osc_colors = ["#e63946" if v >= 0 else "#2a9d8f" for v in df["MACD_OSC"]]
    ax3.bar(df.index, df["MACD_OSC"], color=osc_colors, alpha=0.7, width=1, label="OSC")
    ax3.plot(df.index, df["MACD_DIF"], label="DIF", color="blue", linewidth=1.2)
    ax3.plot(df.index, df["MACD_DEA"], label="DEA", color="orange", linewidth=1.2)
    ax3.axhline(0, color="gray", linestyle="-", linewidth=0.8)
    ax3.set_ylabel("MACD")
    ax3.legend(loc="upper left")
    ax3.grid(True, alpha=0.4)

    # ── 圖四：成交量分析 ─────────────────────────────
    up_days = df["Close"] >= df["Open"]
    bar_colors = ["#e63946" if u else "#2a9d8f" for u in up_days]
    ax4.bar(
        df.index, df["Volume"], color=bar_colors, alpha=0.7, width=1, label="成交量"
    )
    ax4.plot(df.index, df["Vol_MA5"], label="MA5", color="orange", linewidth=1.2)
    ax4.plot(df.index, df["Vol_MA20"], label="MA20", color="royalblue", linewidth=1.2)

    high_vol = df[df["Vol_Ratio"] >= 2]
    if not high_vol.empty:
        ax4.scatter(
            high_vol.index,
            high_vol["Volume"],
            color="darkred",
            zorder=5,
            s=20,
            label="爆量 (量比≥2)",
        )

    ax4.set_ylabel("Volume")
    ax4.set_xlabel("Date")
    ax4.legend(loc="upper left")
    ax4.grid(True, alpha=0.4)

    plt.tight_layout()

    out_path = f"{OUTPUT_DIR}/{_safe_id(stock_id)}.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"💾 已存檔：{out_path}")


def _build_stock_html(stock_id: str, df: pd.DataFrame) -> tuple[str, str]:
    """回傳 (summary_row_html, chart_card_html)。"""
    ret, n_days = calc_period_return(df)
    ret_pct = f"{ret * 100:+.2f}%" if not pd.isna(ret) else "N/A"
    ret_class = "up" if (not pd.isna(ret) and ret >= 0) else "dn"

    img_path = os.path.join(OUTPUT_DIR, f"{_safe_id(stock_id)}.png")
    img_tag = ""
    if os.path.exists(img_path):
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        img_tag = (
            f'<img src="data:image/png;base64,{b64}" alt="{stock_id}" loading="lazy">'
        )

    row = (
        f"<tr>"
        f'<td class="sid">{stock_id}</td>'
        f'<td class="{ret_class}">{ret_pct}</td>'
        f"<td>{n_days} 天</td>"
        f"</tr>"
    )
    card = (
        f'<div class="card">'
        f'<div class="card-header">'
        f'<span class="sid">{stock_id}</span>'
        f'<span class="ret {ret_class}">{ret_pct}</span>'
        f"</div>"
        f"{img_tag}"
        f"</div>"
    )
    return row, card


def generate_html_report(results: list[tuple[str, pd.DataFrame]]):
    """生成自包含 HTML 報告（PNG 以 base64 內嵌），儲存至 docs/index.html。"""
    if not results:
        print("⚠️  沒有任何股票資料，跳過報告生成。")
        return

    template_path = os.path.join(_BASE, "report_template.html")
    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    rows, cards = zip(*[_build_stock_html(sid, df) for sid, df in results])

    html = (
        template.replace(
            "%%GENERATED_AT%%",
            datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        )
        .replace("%%START_DATE%%", START_DATE)
        .replace("%%END_DATE%%", TODAY)
        .replace("%%LOOKBACK_DAYS%%", str(LOOKBACK_DAYS))
        .replace("%%SUMMARY_ROWS%%", "".join(rows))
        .replace("%%CHART_CARDS%%", "".join(cards))
    )

    out_path = os.path.join(DOCS_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"🌐 HTML 報告已生成：{out_path}")


# ==========================================
# 主程式：依序分析並儲存所有股票圖表
# ==========================================
if __name__ == "__main__":
    results = []
    for sid in STOCK_LIST:
        df = analyze_stock(sid)
        if df is not None:
            plot_stock(sid, df)
            results.append((sid, df))

    if results:
        generate_html_report(results)

    print(f"\n✅ 共成功儲存 {len(results)} / {len(STOCK_LIST)} 支股票的圖表。")
