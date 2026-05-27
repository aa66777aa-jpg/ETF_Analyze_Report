import os
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
from datetime import date, timedelta

matplotlib.rcParams["font.family"] = [
    "Heiti TC",
    "Noto Sans CJK TC",
    "Noto Sans TC",
    "Arial Unicode MS",
    "sans-serif",
]
matplotlib.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Report")
os.makedirs(OUTPUT_DIR, exist_ok=True)

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
END_DATE = (date.today() + timedelta(days=1)).isoformat()
START_DATE = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
FETCH_START = (date.today() - timedelta(days=LOOKBACK_DAYS + WARMUP_DAYS)).isoformat()


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
    if isinstance(df.columns, pd.MultiIndex):
        if "Close" in df.columns.get_level_values(0):
            df.columns = df.columns.get_level_values(0)
        else:
            df.columns = df.columns.get_level_values(1)

    # auto_adjust=False 時使用 Adj Close 計算指標，Volume 維持原始值對應 Yahoo Finance
    price = df["Adj Close"] if "Adj Close" in df.columns else df["Close"]

    # --- 威廉指標 (Williams %R) ---
    high_n = df["High"].rolling(window=W_PERIOD).max()
    low_n = df["Low"].rolling(window=W_PERIOD).min()
    df["Williams_%R"] = ((high_n - price) / (high_n - low_n)) * -100

    # --- 多空指標 (BBI) ---
    ma3 = price.rolling(window=3).mean()
    ma6 = price.rolling(window=6).mean()
    ma12 = price.rolling(window=12).mean()
    ma24 = price.rolling(window=24).mean()
    df["BBI"] = (ma3 + ma6 + ma12 + ma24) / 4

    # --- MACD ---
    ema12 = price.ewm(span=12, adjust=False).mean()
    ema26 = price.ewm(span=26, adjust=False).mean()
    df["MACD_DIF"] = ema12 - ema26
    df["MACD_DEA"] = df["MACD_DIF"].ewm(span=9, adjust=False).mean()
    df["MACD_OSC"] = df["MACD_DIF"] - df["MACD_DEA"]

    # --- 成交量分析 ---
    df["Vol_MA5"] = df["Volume"].rolling(window=5).mean()
    df["Vol_MA20"] = df["Volume"].rolling(window=20).mean()
    df["Vol_Ratio"] = df["Volume"] / df["Vol_MA20"]  # 量比（相對 20 日均量）

    df.dropna(inplace=True)

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
    price_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    first_close = df[price_col].iloc[0]
    last_close = df[price_col].iloc[-1]
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
    ann_ret_color = "red" if period_ret >= 0 else "green"

    fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(13, 14), sharex=True)
    fig.suptitle(
        f"{stock_id}  技術指標分析  ({START_DATE} ~ {END_DATE})",
        fontsize=14,
        fontweight="bold",
    )

    # ── 圖一：股價 & BBI ─────────────────────────────
    price_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    ax1.plot(
        df.index, df[price_col], label="收盤價(還原)", color="black", linewidth=1.5
    )
    ax1.plot(df.index, df["BBI"], label="BBI", color="orange", linestyle="--")
    ax1.set_ylabel("Price (TWD)")

    # 年化報酬率標註
    first_price = df[price_col].iloc[0]
    last_price = df[price_col].iloc[-1]
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

    # 量比 >= 2 的日期標上紅點（爆量）
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

    safe_id = stock_id.replace("^", "").replace(".", "_")
    out_path = f"{OUTPUT_DIR}/{safe_id}.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"💾 已存檔：{out_path}")


# ==========================================
# 主程式：依序分析並儲存所有股票圖表
# ==========================================
if __name__ == "__main__":
    success_count = 0
    for sid in STOCK_LIST:
        df = analyze_stock(sid)
        if df is not None:
            ret, n_days = calc_period_return(df)
            ret_str = f"{ret * 100:+.2f}% ({n_days}天)" if not pd.isna(ret) else "N/A"
            print(f"   📈 期間報酬率：{ret_str}")
            plot_stock(sid, df)
            success_count += 1

    print(f"\n✅ 共成功儲存 {success_count} / {len(STOCK_LIST)} 支股票的圖表。")
