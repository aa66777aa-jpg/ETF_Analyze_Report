import base64
import os
from io import BytesIO

import matplotlib.pyplot as plt
import pandas as pd

from config import (
    CMF_OVERBOUGHT,
    CMF_OVERSOLD,
    CMF_PERIOD,
    OUTPUT_DIR,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_PERIOD,
    SCORE_STRONG_BUY,
    SCORE_STRONG_SELL,
    START_DATE,
    TODAY,
    _OVERALL_COLOR,
    _safe_id,
)
from signal_common import _leverage_thresholds, compute_historical_scores


def plot_stock(stock_id: str, df, signal_info: dict) -> str:
    """繪製四格子圖（均線+量 / RSI / CMF 資金流量 / 距高點跌幅）並存檔，回傳 base64 字串。"""
    overall = signal_info["overall"]
    score = signal_info["score"]
    last_price = signal_info["price"]
    is_index = signal_info.get("is_index", False)
    is_inverse = signal_info.get("is_inverse", False)
    leverage = signal_info.get("leverage", 1.0)
    ann_color = _OVERALL_COLOR.get(overall, "#888888")

    lev, plot_dd_strong, plot_dd_mild, plot_dd_near_high, _, _ = _leverage_thresholds(
        leverage
    )

    lev_label = f"×{lev:.0f}" if lev > 1 else ""
    title_tag = (
        "【反向ETF】" if is_inverse else (f"【{lev_label}倍槓桿】" if lev > 1 else "")
    )
    fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(13, 14), sharex=True)
    fig.suptitle(
        f"{stock_id} {title_tag} 定期投入時機分析  ({START_DATE} ~ {TODAY})",
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
    ax1.plot(
        df.index,
        df["MA120"],
        label="MA120",
        color="#264653",
        linewidth=1.2,
        linestyle="--",
    )
    ax1.set_ylabel("Price")
    if is_index:
        ann_text = f"{overall}\n最新收盤：{last_price:.2f}"
    elif is_inverse:
        ann_text = (
            f"【反向ETF】建議：{overall}（{score:+d} 分）\n最新收盤：{last_price:.2f}"
        )
    else:
        ann_text = f"建議：{overall}（{score:+d} 分）\n最新收盤：{last_price:.2f}"
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

    h_scores = compute_historical_scores(df, is_inverse=is_inverse, leverage=leverage)
    buy_idx = h_scores[h_scores >= SCORE_STRONG_BUY].index
    sell_idx = h_scores[h_scores <= SCORE_STRONG_SELL].index
    if not buy_idx.empty:
        ax1.scatter(
            buy_idx,
            df.loc[buy_idx, "Close"],
            marker="^",
            color="#e63946",
            s=20,
            alpha=0.45,
            zorder=5,
            label="歷史買入區",
        )
    if not sell_idx.empty:
        ax1.scatter(
            sell_idx,
            df.loc[sell_idx, "Close"],
            marker="v",
            color="#9b5de5",
            s=20,
            alpha=0.45,
            zorder=5,
            label="歷史賣出區",
        )

    _hi = signal_info.get("holding_info", {})
    if _hi:
        ax1.axhline(
            _hi["cost"],
            color="#f4a261",
            linestyle="-.",
            linewidth=1.5,
            label=f"持倉成本 {_hi['cost']:.2f}",
            alpha=0.85,
        )
        ax1.axhline(
            _hi["target_price"],
            color="#9b5de5",
            linestyle="-.",
            linewidth=1.5,
            label=f"停利目標 {_hi['target_price']:.2f} (+{_hi['target_pct']:.0f}%)",
            alpha=0.85,
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

    # ── 圖三：CMF 資金流量 ──────────────────────────────
    ax3.plot(
        df.index,
        df["CMF"],
        label=f"CMF ({CMF_PERIOD})",
        color="purple",
        linewidth=1.2,
    )
    ax3.axhspan(CMF_OVERBOUGHT, 1, color="#2a9d8f", alpha=0.07)
    ax3.axhspan(-1, CMF_OVERSOLD, color="#e63946", alpha=0.07)
    ax3.axhline(
        CMF_OVERBOUGHT,
        color="#2a9d8f",
        linestyle=":",
        linewidth=1,
        label=f"資金流入過熱 ({CMF_OVERBOUGHT:+.2f})",
    )
    ax3.axhline(
        CMF_OVERSOLD,
        color="#e63946",
        linestyle=":",
        linewidth=1,
        label=f"資金流出賣壓 ({CMF_OVERSOLD:+.2f})",
    )
    ax3.axhline(0, color="gray", linestyle="-", linewidth=0.5)
    ax3.set_ylabel("CMF")
    cmf_max_abs = df["CMF"].abs().max()
    cmf_bound = (
        min(1.0, max(0.6, float(cmf_max_abs) * 1.15)) if pd.notna(cmf_max_abs) else 0.6
    )
    ax3.set_ylim(-cmf_bound, cmf_bound)
    ax3.legend(loc="upper left")
    ax3.grid(True, alpha=0.4)

    # ── 圖四：距 52 週高點跌幅 ──────────────────────────
    dd = df["Drawdown"]
    ax4.plot(df.index, dd, color="#264653", linewidth=1.2, label="距高點跌幅")
    if is_inverse:
        ax4.fill_between(
            df.index,
            dd,
            0,
            where=(dd >= plot_dd_near_high),
            color="#e63946",
            alpha=0.35,
            label=f"加碼區（市場跌勢，距高點<{abs(plot_dd_near_high):.0f}%）",
        )
        ax4.fill_between(
            df.index,
            dd,
            0,
            where=(dd > plot_dd_mild) & (dd < plot_dd_near_high),
            color="#aaaaaa",
            alpha=0.15,
            label=f"正常區（{abs(plot_dd_near_high):.0f}~{abs(plot_dd_mild):.0f}%）",
        )
        ax4.fill_between(
            df.index,
            dd,
            0,
            where=(dd > plot_dd_strong) & (dd <= plot_dd_mild),
            color="#f4a261",
            alpha=0.3,
            label=f"謹慎區（市場反彈，{abs(plot_dd_mild):.0f}~{abs(plot_dd_strong):.0f}%）",
        )
        ax4.fill_between(
            df.index,
            dd,
            0,
            where=(dd <= plot_dd_strong),
            color="#2a9d8f",
            alpha=0.2,
            label=f"暫緩區（市場強勁反彈，>{abs(plot_dd_strong):.0f}%）",
        )
    else:
        ax4.fill_between(
            df.index,
            dd,
            0,
            where=(dd <= plot_dd_strong),
            color="#e63946",
            alpha=0.35,
            label=f"積極加碼區（>{abs(plot_dd_strong):.0f}%）",
        )
        ax4.fill_between(
            df.index,
            dd,
            0,
            where=(dd > plot_dd_strong) & (dd <= plot_dd_mild),
            color="#f4a261",
            alpha=0.3,
            label=f"考慮加碼區（{abs(plot_dd_mild):.0f}~{abs(plot_dd_strong):.0f}%）",
        )
        ax4.fill_between(
            df.index,
            dd,
            0,
            where=(dd > plot_dd_mild) & (dd < plot_dd_near_high),
            color="#aaaaaa",
            alpha=0.15,
            label=f"正常區（{abs(plot_dd_near_high):.0f}~{abs(plot_dd_mild):.0f}%）",
        )
        ax4.fill_between(
            df.index,
            dd,
            0,
            where=(dd >= plot_dd_near_high),
            color="#2a9d8f",
            alpha=0.15,
            label=f"接近高點（<{abs(plot_dd_near_high):.0f}%）",
        )
    ax4.axhline(plot_dd_mild, color="#f4a261", linestyle="--", linewidth=1)
    ax4.axhline(plot_dd_strong, color="#e63946", linestyle="--", linewidth=1)
    ax4.axhline(plot_dd_near_high, color="#2a9d8f", linestyle=":", linewidth=1)
    ax4.axhline(0, color="gray", linewidth=0.5)
    ax4.set_ylabel("距高點 (%)")
    ax4.set_xlabel("Date")
    ax4.legend(loc="lower left", fontsize=8)
    ax4.grid(True, alpha=0.4)

    plt.tight_layout()

    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    finally:
        plt.close(fig)

    buf.seek(0)
    img_bytes = buf.read()

    out_path = os.path.join(OUTPUT_DIR, f"{_safe_id(stock_id)}.png")
    with open(out_path, "wb") as f:
        f.write(img_bytes)
    print(f"💾 已存檔：{out_path}")

    return base64.b64encode(img_bytes).decode()
