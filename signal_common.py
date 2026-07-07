import pandas as pd

from config import (
    CMF_OVERBOUGHT,
    CMF_OVERSOLD,
    DD_MILD,
    DD_NEAR_HIGH,
    DD_STRONG,
    HOLDINGS,
    MA60_HIGH,
    MA60_LOW,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
)


def _score_to_overall(score: int) -> str:
    if score >= 2:
        return "積極加碼"
    elif score == 1:
        return "考慮加碼"
    elif score >= -2:
        return "觀望"
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


def _classify_cmf(cmf_raw, inverse: bool = False) -> tuple[str, str, int]:
    """依 CMF（資金流量）分類為 (訊號, 說明, 分數)。

    刻意採用與 RSI 相同的逆向（均值回歸）解讀：資金流出視為短期賣壓宣洩、
    逢低承接機會；資金流入視為買盤過熱。這與 CMF 傳統上「順勢確認」的解讀
    方向相反，是配合本工具「均值回歸」評分框架的刻意選擇。
    inverse=True 時用於反向型 ETF，方向相反（本檔資金流入代表原型重挫）。
    """
    if pd.isna(cmf_raw):
        return ("正常", "成交量不足（CMF 無法計算）", 0)
    cmf = float(cmf_raw)
    if inverse:
        if cmf >= CMF_OVERBOUGHT:
            return ("加碼", f"資金流入本檔（反向ETF CMF {cmf:.2f}，代表原型重挫）", 1)
        elif cmf <= CMF_OVERSOLD:
            return ("暫緩", f"資金流出本檔（反向ETF CMF {cmf:.2f}，代表原型走強）", -1)
        else:
            return ("正常", f"中性（CMF {cmf:.2f}）", 0)
    else:
        if cmf <= CMF_OVERSOLD:
            return ("加碼", f"資金流出（CMF {cmf:.2f}，賣壓重）", 1)
        elif cmf >= CMF_OVERBOUGHT:
            return ("暫緩", f"資金流入（CMF {cmf:.2f}，買盤過熱）", -1)
        else:
            return ("正常", f"中性（CMF {cmf:.2f}）", 0)


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

    cmf = df["CMF"]
    cmf_valid = cmf.notna()
    scores += sign * (cmf_valid & (cmf <= CMF_OVERSOLD)).astype(int)
    scores -= sign * (cmf_valid & (cmf >= CMF_OVERBOUGHT)).astype(int)

    return scores
