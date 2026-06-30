import pandas as pd

from config import (
    DD_MILD,
    DD_NEAR_HIGH,
    DD_STRONG,
    HOLDINGS,
    MA60_HIGH,
    MA60_LOW,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    WR_OVERBOUGHT,
    WR_OVERSOLD,
)


def _score_to_overall(score: int) -> str:
    if score >= 2:
        return "積極加碼"
    elif score == 1:
        return "考慮加碼"
    elif score == 0:
        return "正常定期投入"
    elif score == -1:
        return "謹慎觀察"
    elif score == -2:
        return "暫緩加碼"
    elif score == -3:
        return "考慮減碼"
    else:
        return "積極減碼"


def _sell_resonance(signals: dict) -> tuple[str, str]:
    sell_count = sum(1 for v in signals.values() if v[0] == "暫緩")
    if sell_count >= 3:
        return f"強力共振 ({sell_count}/4)", "sell-strong"
    elif sell_count >= 2:
        return f"共振 ({sell_count}/4)", "sell"
    elif sell_count == 1:
        return f"{sell_count}/4", "neutral"
    else:
        return "—", "neutral"


def _holding_info(stock_id: str, price: float) -> dict:
    if not stock_id or stock_id not in HOLDINGS:
        return {}
    h = HOLDINGS[stock_id]
    cost_raw = h.get("cost")
    if cost_raw is None:
        print(f"⚠️  HOLDINGS[{stock_id!r}] 缺少 cost 欄位，跳過持倉追蹤。")
        return {}
    if float(cost_raw) == 0:
        print(f"⚠️  HOLDINGS[{stock_id!r}] cost 為 0，無法計算損益，跳過持倉追蹤。")
        return {}
    cost = float(cost_raw)
    target_pct = float(h.get("target_pct", 20))
    target_price = cost * (1 + target_pct / 100)
    pnl_pct = (price - cost) / cost * 100
    return {
        "cost": cost,
        "target_pct": target_pct,
        "target_price": target_price,
        "price": price,
        "pnl_pct": pnl_pct,
        "reached_target": price >= target_price,
    }


def _leverage_thresholds(leverage: float) -> tuple:
    """回傳 (lev, dd_strong, dd_mild, dd_near_high, ma60_low, ma60_high)。"""
    lev = max(leverage, 1.0)
    return (
        lev,
        DD_STRONG * lev,
        DD_MILD * lev,
        DD_NEAR_HIGH * lev,
        MA60_LOW * lev,
        MA60_HIGH * lev,
    )


def compute_historical_scores(
    df: pd.DataFrame, is_inverse: bool = False, leverage: float = 1.0
) -> pd.Series:
    """向量化計算歷史每日評分，供圖表標記歷史買賣訊號使用。
    is_inverse=True 時，所有訊號方向相反（反向型 ETF）。
    leverage > 1 時，DD 與 MA60 閾值等比放大（槓桿型 ETF）。
    """
    scores = pd.Series(0, index=df.index, dtype=int)
    sign = -1 if is_inverse else 1
    lev, dd_strong, dd_mild, dd_near_high, ma60_low, ma60_high = _leverage_thresholds(
        leverage
    )

    scores += sign * (df["RSI"] < RSI_OVERSOLD).astype(int)
    scores -= sign * (df["RSI"] > RSI_OVERBOUGHT).astype(int)

    scores += sign * (df["Drawdown"] <= dd_mild).astype(int)
    scores += sign * (df["Drawdown"] <= dd_strong).astype(int)
    scores -= sign * (df["Drawdown"] >= dd_near_high).astype(int)
    if is_inverse:
        scores += (df["Drawdown"] >= dd_near_high).astype(int)

    ma60_slope = df["MA60"].diff(20)
    if is_inverse:
        scores += ((df["MA60_Dev"] >= ma60_high) & (ma60_slope > 0)).astype(int)
        scores -= (df["MA60_Dev"] <= ma60_low).astype(int)
    else:
        scores += ((df["MA60_Dev"] <= ma60_low) & (ma60_slope > 0)).astype(int)
        scores -= (df["MA60_Dev"] >= ma60_high).astype(int)

    wr = df["Williams_%R"]
    wr_valid = wr.notna()
    scores += sign * (wr_valid & (wr <= WR_OVERSOLD)).astype(int)
    scores -= sign * (wr_valid & (wr >= WR_OVERBOUGHT)).astype(int)

    return scores
