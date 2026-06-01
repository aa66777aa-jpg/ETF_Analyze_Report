import base64
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from io import BytesIO

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
    "Microsoft JhengHei",
    "Microsoft YaHei",
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
    "00735.TW",
    "^TWII",
    "^DJI",
    "^GSPC",
    "^IXIC",
    # 繼續新增你想觀察的股票代號...
]

LOOKBACK_DAYS = 365  # 顯示的觀察天數
WARMUP_DAYS = 180  # 預先多抓的資料天數（確保 MA120 有足夠暖機）
RSI_PERIOD = 14  # RSI 回看天數
W_PERIOD = 14  # 威廉指標回看天數
MA_PERIODS = (20, 60, 120)  # 移動均線參數
HIGH_WINDOW = 252  # 52 週高點視窗（約 1 年交易日）

# 訊號閾值常數
RSI_OVERSOLD = 35  # RSI 超賣線（加碼）
RSI_OVERBOUGHT = 70  # RSI 過熱線（暫緩）
DD_STRONG = -15  # 距高點跌幅：積極加碼區（+2 分）
DD_MILD = -8  # 距高點跌幅：考慮加碼區（+1 分）
DD_NEAR_HIGH = -3  # 距高點跌幅：接近高點（-1 分）
MA60_LOW = -5  # 低於 MA60 偏差（加碼）
MA60_HIGH = 8  # 高於 MA60 偏差（暫緩）
WR_OVERSOLD = -80  # Williams %R 超賣線（加碼）
WR_OVERBOUGHT = -20  # Williams %R 超買線（暫緩）

TODAY = date.today().isoformat()
END_DATE = (date.today() + timedelta(days=1)).isoformat()
START_DATE = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
FETCH_START = (date.today() - timedelta(days=LOOKBACK_DAYS + WARMUP_DAYS)).isoformat()

# 各建議對應的顏色（台股慣例：紅 = 買機會，綠 = 過熱謹慎）
_OVERALL_COLOR = {
    "積極加碼": "#e63946",
    "考慮加碼": "#f4a261",
    "正常定期投入": "#888888",
    "謹慎觀察": "#457b9d",
    "暫緩加碼": "#2a9d8f",
}
_OVERALL_CLASS = {
    "積極加碼": "add-strong",
    "考慮加碼": "add",
    "正常定期投入": "neutral",
    "謹慎觀察": "caution",
    "暫緩加碼": "wait",
}
_SIG_CLASS = {"加碼": "add", "暫緩": "wait", "正常": "neutral"}


def _safe_id(stock_id: str) -> str:
    return stock_id.replace("^", "").replace(".", "_")


def _is_index(stock_id: str) -> bool:
    return stock_id.startswith("^")


def analyze_stock(stock_id: str):
    """下載並計算單支股票的技術指標，回傳 DataFrame；若資料不足或發生錯誤則回傳 None。"""
    try:
        return _analyze_stock_impl(stock_id)
    except Exception as exc:
        print(f"❌ {stock_id} 發生未預期錯誤，已跳過：{exc}")
        return None


def _analyze_stock_impl(stock_id: str):
    print(f"\n📥 正在下載：{stock_id} ...")
    df = yf.download(
        stock_id, start=FETCH_START, end=END_DATE, progress=False, auto_adjust=True
    )

    if df.empty:
        print(f"⚠️  {stock_id} 無資料，跳過。")
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    price = df["Close"]

    # --- RSI (Wilder's smoothing) ---
    delta = price.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(
        alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False
    ).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # --- 移動均線（min_periods=半週期，讓成立未滿的 ETF 也能部分計算）---
    for p in MA_PERIODS:
        df[f"MA{p}"] = price.rolling(window=p, min_periods=max(p // 2, 10)).mean()

    # --- 價格相對 MA60 的偏差 (%) ---
    df["MA60_Dev"] = (price - df["MA60"]) / df["MA60"] * 100

    # --- 距 52 週高點的跌幅 (%) ---
    df["High_252"] = price.rolling(window=HIGH_WINDOW, min_periods=60).max()
    df["Drawdown"] = (price - df["High_252"]) / df["High_252"] * 100

    # --- 威廉指標 (Williams %R) ---
    high_n = df["High"].rolling(window=W_PERIOD).max()
    low_n = df["Low"].rolling(window=W_PERIOD).min()
    range_n = (high_n - low_n).replace(0, float("nan"))  # 橫盤無波動時避免除以零
    df["Williams_%R"] = ((high_n - price) / range_n) * -100

    # --- 成交量比率（相對 20 日均量）---
    df["Vol_MA20"] = df["Volume"].rolling(window=20, min_periods=5).mean()
    df["Vol_Ratio"] = (df["Volume"] / df["Vol_MA20"]).fillna(1.0)

    # MA120 不列入必要欄位，讓成立未滿 120 天的 ETF 也能繼續分析
    df = df.dropna(subset=["RSI", "MA60", "Williams_%R"])

    if df.empty:
        print(f"⚠️  {stock_id} dropna 後無資料，跳過。")
        return None

    df = df[df.index >= pd.Timestamp(START_DATE)]

    if df.empty:
        print(f"⚠️  {stock_id} 截回觀察區間後無資料，跳過。")
        return None

    return df


def generate_signal(df: pd.DataFrame) -> dict:
    """根據最新一日數據判斷 ETF 定期投入的加碼時機。

    評分邏輯（距高點跌幅最高 +2，其餘各項 -1 / 0 / +1）：
      +2 = 強力加碼訊號（距高點明顯回落，DD_STRONG）
      +1 = 加碼訊號（市場相對低估）
      -1 = 暫緩訊號（市場相對高估）
       0 = 正常

    綜合建議：
      score >= 2  → 積極加碼
      score == 1  → 考慮加碼
      score == 0  → 正常定期投入
      score == -1 → 謹慎觀察
      score <= -2 → 暫緩加碼

    最高分：+5（距高點明顯回落 +2，其餘三項均 +1）
    最低分：-4（四項指標均 -1）
    """
    latest = df.iloc[-1]
    price = float(latest["Close"])
    signals = {}

    # --- RSI ---
    rsi = float(latest["RSI"])
    if rsi < RSI_OVERSOLD:
        signals["rsi"] = ("加碼", f"超賣（RSI {rsi:.1f}）", 1)
    elif rsi > RSI_OVERBOUGHT:
        signals["rsi"] = ("暫緩", f"過熱（RSI {rsi:.1f}）", -1)
    else:
        signals["rsi"] = ("正常", f"中性（RSI {rsi:.1f}）", 0)

    # --- 距 52 週高點跌幅（明顯回落 +2 分，有所回落 +1 分） ---
    drawdown = float(latest["Drawdown"])
    if drawdown <= DD_STRONG:
        signals["drawdown"] = ("加碼", f"距高點 {drawdown:.1f}%（明顯回落）", 2)
    elif drawdown <= DD_MILD:
        signals["drawdown"] = ("加碼", f"距高點 {drawdown:.1f}%（有所回落）", 1)
    elif drawdown >= DD_NEAR_HIGH:
        signals["drawdown"] = ("暫緩", f"距高點僅 {drawdown:.1f}%（接近高點）", -1)
    else:
        signals["drawdown"] = ("正常", f"距高點 {drawdown:.1f}%", 0)

    # --- 價格 vs MA60 ---
    ma60_dev = float(latest["MA60_Dev"])
    if ma60_dev <= MA60_LOW:
        signals["ma60"] = ("加碼", f"低於 MA60 {ma60_dev:.1f}%（均線下方）", 1)
    elif ma60_dev >= MA60_HIGH:
        signals["ma60"] = ("暫緩", f"高於 MA60 +{ma60_dev:.1f}%（過度延伸）", -1)
    else:
        signals["ma60"] = ("正常", f"MA60 偏差 {ma60_dev:+.1f}%", 0)

    # --- Williams %R ---
    wr = float(latest["Williams_%R"])
    if wr <= WR_OVERSOLD:
        signals["williams"] = ("加碼", f"超賣（{wr:.1f}）", 1)
    elif wr >= WR_OVERBOUGHT:
        signals["williams"] = ("暫緩", f"超買（{wr:.1f}）", -1)
    else:
        signals["williams"] = ("正常", f"中性（{wr:.1f}）", 0)

    score = sum(v[2] for v in signals.values())

    if score >= 2:
        overall = "積極加碼"
    elif score == 1:
        overall = "考慮加碼"
    elif score == 0:
        overall = "正常定期投入"
    elif score == -1:
        overall = "謹慎觀察"
    else:
        overall = "暫緩加碼"

    return {"signals": signals, "score": score, "overall": overall, "price": price}


def generate_index_context(df: pd.DataFrame) -> dict:
    """指數（^ 開頭）不給加碼建議，改輸出市場環境標籤供參考。"""
    latest = df.iloc[-1]
    rsi = float(latest["RSI"])
    drawdown = float(latest["Drawdown"])
    ma60_dev = float(latest["MA60_Dev"])
    wr = float(latest["Williams_%R"])

    bull = sum([rsi > 60, drawdown > DD_NEAR_HIGH, ma60_dev > 3, wr >= WR_OVERBOUGHT])
    bear = sum([rsi < 45, drawdown <= DD_MILD, ma60_dev < -3, wr <= WR_OVERSOLD])

    if bull >= 3:
        env, env_cls = "偏多", "wait"
    elif bear >= 3:
        env, env_cls = "偏空", "add"
    else:
        env, env_cls = "中性", "neutral"

    return {
        "is_index": True,
        "overall": f"市場環境：{env}",
        "overall_cls": env_cls,
        "score": 0,
        "price": float(latest["Close"]),
        "signals": {
            "rsi": (f"RSI {rsi:.0f}", f"RSI={rsi:.1f}", 0),
            "drawdown": (f"{drawdown:.1f}%", f"距高點跌幅={drawdown:.1f}%", 0),
            "ma60": (f"MA60 {ma60_dev:+.1f}%", f"MA60偏差={ma60_dev:.1f}%", 0),
            "williams": (f"W%R {wr:.0f}", f"Williams %R={wr:.1f}", 0),
        },
    }


def plot_stock(stock_id: str, df: pd.DataFrame, signal_info: dict) -> str:
    """繪製四格子圖（均線+量 / RSI / Williams %R / 距高點跌幅）並存檔。"""
    overall = signal_info["overall"]
    score = signal_info["score"]
    last_price = signal_info["price"]
    is_index = signal_info.get("is_index", False)
    ann_color = _OVERALL_COLOR.get(overall, "#888888")

    fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(13, 14), sharex=True)
    fig.suptitle(
        f"{stock_id}  定期投入時機分析  ({START_DATE} ~ {TODAY})",
        fontsize=14,
        fontweight="bold",
    )

    # ── 圖一：收盤價 + 移動均線 ─────────────────────────
    ax1.plot(df.index, df["Close"], label="收盤價", color="black", linewidth=1.5)
    ax1.plot(
        df.index, df["MA20"], label="MA20", color="#f4a261", linewidth=1, linestyle="--"
    )
    ax1.plot(
        df.index,
        df["MA60"],
        label="MA60",
        color="#e76f51",
        linewidth=1.2,
        linestyle="--",
    )
    if df["MA120"].notna().any():
        ax1.plot(
            df.index,
            df["MA120"],
            label="MA120",
            color="#264653",
            linewidth=1.2,
            linestyle="--",
        )
    ax1.set_ylabel("Price")
    ann_text = (
        f"{overall}\n最新收盤：{last_price:.2f}"
        if is_index
        else f"建議：{overall}（{score:+d} 分）\n最新收盤：{last_price:.2f}"
    )
    ax1.annotate(
        ann_text,
        xy=(df.index[-1], last_price),
        xytext=(-10, 10),
        textcoords="offset points",
        ha="right",
        fontsize=9,
        color=ann_color,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=ann_color, alpha=0.8),
    )
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.4)

    # ── 成交量（副 y 軸，壓縮至圖底 20%）────────────────
    ax1v = ax1.twinx()
    price_chg = df["Close"].diff().fillna(0)
    vol_colors = ["#aec6e8" if c >= 0 else "#e8b4aa" for c in price_chg]
    ax1v.bar(df.index, df["Vol_Ratio"], color=vol_colors, alpha=0.28, width=1, zorder=0)
    ax1v.axhline(1.0, color="gray", linestyle=":", linewidth=0.6, alpha=0.5)
    vol_top = max(df["Vol_Ratio"].quantile(0.97) * 5, 5)
    ax1v.set_ylim(0, vol_top)
    ax1v.set_ylabel("量比", color="#aaa", fontsize=7)
    ax1v.tick_params(axis="y", labelcolor="#aaa", labelsize=6)

    # ── 圖二：RSI ────────────────────────────────────────
    ax2.plot(
        df.index, df["RSI"], label=f"RSI ({RSI_PERIOD})", color="#457b9d", linewidth=1.2
    )
    ax2.axhspan(0, RSI_OVERSOLD, color="#e63946", alpha=0.07)
    ax2.axhspan(RSI_OVERBOUGHT, 100, color="#2a9d8f", alpha=0.07)
    ax2.axhline(
        RSI_OVERBOUGHT,
        color="#2a9d8f",
        linestyle=":",
        linewidth=1,
        label=f"過熱 ({RSI_OVERBOUGHT})",
    )
    ax2.axhline(
        RSI_OVERSOLD,
        color="#e63946",
        linestyle=":",
        linewidth=1,
        label=f"超賣 ({RSI_OVERSOLD})",
    )
    ax2.axhline(50, color="gray", linestyle="-", linewidth=0.5)
    ax2.set_ylabel("RSI")
    ax2.set_ylim(0, 100)
    ax2.legend(loc="upper left")
    ax2.grid(True, alpha=0.4)

    # ── 圖三：Williams %R ────────────────────────────────
    ax3.plot(
        df.index,
        df["Williams_%R"],
        label=f"Williams %R ({W_PERIOD})",
        color="purple",
        linewidth=1.2,
    )
    ax3.axhspan(-100, WR_OVERSOLD, color="#e63946", alpha=0.07)
    ax3.axhspan(WR_OVERBOUGHT, 0, color="#2a9d8f", alpha=0.07)
    ax3.axhline(
        WR_OVERBOUGHT,
        color="#2a9d8f",
        linestyle=":",
        linewidth=1,
        label=f"超買 ({WR_OVERBOUGHT})",
    )
    ax3.axhline(
        WR_OVERSOLD,
        color="#e63946",
        linestyle=":",
        linewidth=1,
        label=f"超賣 ({WR_OVERSOLD})",
    )
    ax3.set_ylabel("Williams %R")
    ax3.set_ylim(-105, 5)
    ax3.legend(loc="upper left")
    ax3.grid(True, alpha=0.4)

    # ── 圖四：距 52 週高點跌幅 ──────────────────────────
    dd = df["Drawdown"].fillna(0)
    ax4.plot(df.index, dd, color="#264653", linewidth=1.2, label="距高點跌幅")
    ax4.fill_between(
        df.index,
        dd,
        0,
        where=(dd <= DD_STRONG),
        color="#e63946",
        alpha=0.35,
        label=f"積極加碼區（>{abs(DD_STRONG)}%）",
    )
    ax4.fill_between(
        df.index,
        dd,
        0,
        where=(dd > DD_STRONG) & (dd <= DD_MILD),
        color="#f4a261",
        alpha=0.3,
        label=f"考慮加碼區（{abs(DD_MILD)}~{abs(DD_STRONG)}%）",
    )
    ax4.fill_between(
        df.index,
        dd,
        0,
        where=(dd > DD_MILD) & (dd < DD_NEAR_HIGH),
        color="#aaaaaa",
        alpha=0.15,
        label=f"正常區（{abs(DD_NEAR_HIGH)}~{abs(DD_MILD)}%）",
    )
    ax4.fill_between(
        df.index,
        dd,
        0,
        where=(dd >= DD_NEAR_HIGH),
        color="#2a9d8f",
        alpha=0.15,
        label=f"接近高點（<{abs(DD_NEAR_HIGH)}%）",
    )
    ax4.axhline(DD_MILD, color="#f4a261", linestyle="--", linewidth=1)
    ax4.axhline(DD_STRONG, color="#e63946", linestyle="--", linewidth=1)
    ax4.axhline(DD_NEAR_HIGH, color="#2a9d8f", linestyle=":", linewidth=1)
    ax4.axhline(0, color="gray", linewidth=0.5)
    ax4.set_ylabel("距高點 (%)")
    ax4.set_xlabel("Date")
    ax4.legend(loc="lower left", fontsize=8)
    ax4.grid(True, alpha=0.4)

    plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    buf.seek(0)
    img_bytes = buf.read()

    out_path = os.path.join(OUTPUT_DIR, f"{_safe_id(stock_id)}.png")
    with open(out_path, "wb") as f:
        f.write(img_bytes)
    print(f"💾 已存檔：{out_path}")

    return base64.b64encode(img_bytes).decode()


def _build_stock_html(
    stock_id: str, df: pd.DataFrame, signal_info: dict, img_b64: str = ""
) -> tuple[str, str]:
    """回傳 (summary_row_html, chart_card_html)。"""
    overall = signal_info["overall"]
    score = signal_info["score"]
    signals = signal_info["signals"]
    is_index = signal_info.get("is_index", False)

    if is_index:
        overall_cls = signal_info.get("overall_cls", "neutral")
    else:
        overall_cls = _OVERALL_CLASS.get(overall, "neutral")

    img_tag = ""
    if img_b64:
        img_tag = f'<img src="data:image/png;base64,{img_b64}" alt="{stock_id}" loading="lazy">'

    if is_index:

        def idx_td(key: str) -> str:
            val, reason, _ = signals[key]
            return f'<td class="neutral" title="{reason}">{val}</td>'

        row = (
            f"<tr>"
            f'<td class="sid">{stock_id} <span class="index-badge">指數</span></td>'
            f'<td class="{overall_cls} overall">{overall}</td>'
            f"{idx_td('rsi')}"
            f"{idx_td('drawdown')}"
            f"{idx_td('ma60')}"
            f"{idx_td('williams')}"
            f"</tr>"
        )
    else:

        def sig_td(key: str) -> str:
            sig, reason, _ = signals[key]
            cls = _SIG_CLASS.get(sig, "neutral")
            return f'<td class="{cls}" title="{reason}">{sig}</td>'

        row = (
            f"<tr>"
            f'<td class="sid">{stock_id}</td>'
            f'<td class="{overall_cls} overall">{overall}&nbsp;({score:+d})</td>'
            f"{sig_td('rsi')}"
            f"{sig_td('drawdown')}"
            f"{sig_td('ma60')}"
            f"{sig_td('williams')}"
            f"</tr>"
        )

    card = (
        f'<div class="card">'
        f'<div class="card-header">'
        f'<span class="sid">{stock_id}</span>'
        f'<span class="sig {overall_cls}">{overall}</span>'
        f"</div>"
        f"{img_tag}"
        f"</div>"
    )
    return row, card


def generate_html_report(results: list[tuple[str, pd.DataFrame, dict, str]]):
    """生成自包含 HTML 報告（PNG 以 base64 內嵌），儲存至 docs/index.html。"""
    if not results:
        print("⚠️  沒有任何股票資料，跳過報告生成。")
        return

    template_path = os.path.join(_BASE, "report_template.html")
    if not os.path.exists(template_path):
        print(f"❌ 找不到報告範本：{template_path}，跳過 HTML 生成。")
        return
    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    rows, cards = zip(
        *[_build_stock_html(sid, df, sig, b64) for sid, df, sig, b64 in results]
    )

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
# 主程式
# ==========================================
if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=4) as executor:
        dfs = list(executor.map(analyze_stock, STOCK_LIST))

    results = []
    for sid, df in zip(STOCK_LIST, dfs):
        if df is not None:
            signal_info = (
                generate_index_context(df) if _is_index(sid) else generate_signal(df)
            )
            b64 = plot_stock(sid, df, signal_info)
            results.append((sid, df, signal_info, b64))

    if results:
        generate_html_report(results)

    print(f"\n✅ 共成功儲存 {len(results)} / {len(STOCK_LIST)} 支股票的圖表。")
