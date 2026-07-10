import pandas as pd

from config import (
    CMF_OVERBOUGHT,
    CMF_OVERSOLD,
    CMF_REVERSAL_WINDOW,
    CMF_SCORE_WEIGHT,
    DD_MILD,
    DD_NEAR_HIGH,
    DD_STRONG,
    HOLDINGS,
    MA60_HIGH,
    MA60_LOW,
    MA60_SLOPE_WINDOW,
    MOMENTUM_CAP,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    SCORE_BUY,
    SCORE_STRONG_BUY,
    SCORE_STRONG_SELL,
)


def _score_to_overall(score: int) -> str:
    if score >= SCORE_STRONG_BUY:
        return "積極加碼"
    elif score == SCORE_BUY:
        return "考慮加碼"
    elif score >= -1:
        return "觀望"
    elif score <= SCORE_STRONG_SELL:
        return "積極減碼"
    else:
        return "考慮減碼"


def _combine_score(signals: dict) -> int:
    """將 RSI / 距高點跌幅 / MA60 偏差合併為單一「動能」子分數（上限 ±MOMENTUM_CAP），
    再與 CMF（資金流，加權至同樣的量級）各佔一半權重相加。

    RSI、距高點跌幅、MA60 偏差三項本質上都是價格動能的不同量尺、彼此高度相關，
    若各自獨立計分再直接加總，等於把同一波漲跌重複計分三次；改為先合併、
    再與資金流量（CMF，成交量面，資訊來源不同）各半加總，避免動能面訊號互相
    疊加膨脹分數。接受完整 signals dict（而非個別分數）以避免呼叫端誤植參數順序。
    """
    momentum = signals["rsi"][2] + signals["drawdown"][2] + signals["ma60"][2]
    momentum = max(-MOMENTUM_CAP, min(MOMENTUM_CAP, momentum))
    return momentum + signals["cmf"][2] * CMF_SCORE_WEIGHT


def _resonance(signals: dict, target_sig: str, cls_prefix: str) -> tuple[str, str]:
    count = sum(1 for v in signals.values() if v[0] == target_sig)
    if count >= 3:
        return f"強力共振 ({count}/4)", f"{cls_prefix}-strong"
    elif count >= 2:
        return f"共振 ({count}/4)", cls_prefix
    elif count == 1:
        return f"{count}/4", "neutral"
    else:
        return "—", "neutral"


def _sell_resonance(signals: dict) -> tuple[str, str]:
    return _resonance(signals, "暫緩", "sell")


def _buy_resonance(signals: dict) -> tuple[str, str]:
    """買點共振：邏輯與 _sell_resonance 對稱，以紅色（add）系列標示。"""
    return _resonance(signals, "加碼", "add")


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


def _cmf_exhaustion(cmf, cmf_delta, price_delta):
    """判斷「力竭確認」：CMF 是否已跨越超賣/超買閾值，且相對
    CMF_REVERSAL_WINDOW 日前已開始反轉，同期價格尚未搶先反應。

    同時支援純量（float，供 _classify_cmf 逐日單一判斷）與向量化
    （pd.Series，供 compute_historical_scores / compute_historical_buy_resonance
    批次計算）兩種呼叫方式，避免三處各自重寫同一套判斷邏輯而互相脫節。
    NaN 比較（>、<=...）在 Python 純量與 pandas 皆會自然回傳 False，
    故不需額外的 notna 判斷。
    """
    outflow_exhausted = (cmf <= CMF_OVERSOLD) & (cmf_delta > 0) & (price_delta <= 0)
    inflow_exhausted = (cmf >= CMF_OVERBOUGHT) & (cmf_delta < 0) & (price_delta >= 0)
    return outflow_exhausted, inflow_exhausted


def _classify_cmf(df: pd.DataFrame, inverse: bool = False) -> tuple[str, str, int]:
    """依 CMF（資金流量）分類為 (訊號, 說明, 分數)。

    刻意採用與 RSI 相同的逆向（均值回歸）解讀：資金流出視為短期賣壓宣洩、
    逢低承接機會；資金流入視為買盤過熱。這與 CMF 傳統上「順勢確認」的解讀
    方向相反，是配合本工具「均值回歸」評分框架的刻意選擇。

    單純比較 CMF 絕對值容易在賣壓仍加速流出時「接刀」、或買盤仍強勁流入時
    提早喊停，因此除了跨越 CMF_OVERSOLD / CMF_OVERBOUGHT 幅度門檻，還要求
    「力竭確認」：CMF 相對 CMF_REVERSAL_WINDOW 日前已經開始反轉（流出趨緩 / 流入趨緩），
    且同期價格尚未搶先反應（仍偏弱 / 仍在高檔），才視為真正訊號，否則僅標記
    為觀察中、不計分。反轉回看天數刻意選用比 CMF_PERIOD 短的窗口——若兩者
    相同，滾動窗口本身的長度會讓「相對 N 日前回升」與「仍在超賣/超買區」
    幾乎不可能同時成立，回測顯示會讓此訊號形同虛設。inverse=True 時用於
    反向型 ETF，維持既有的加碼／暫緩對應方向不變（本檔資金流入代表原型
    重挫），只是同樣套用力竭確認閘門。
    """
    cmf_raw = df["CMF"].iloc[-1]
    if pd.isna(cmf_raw):
        return ("正常", "成交量不足（CMF 無法計算）", 0)
    cmf = float(cmf_raw)

    cmf_delta = df["CMF"].diff(CMF_REVERSAL_WINDOW).iloc[-1]
    price_delta = df["Close"].diff(CMF_REVERSAL_WINDOW).iloc[-1]
    outflow_exhausted, inflow_exhausted = _cmf_exhaustion(cmf, cmf_delta, price_delta)
    outflow_zone = cmf <= CMF_OVERSOLD
    inflow_zone = cmf >= CMF_OVERBOUGHT

    if inverse:
        if inflow_exhausted:
            return (
                "加碼",
                f"資金流入動能趨緩（反向ETF CMF {cmf:.2f}，原型賣壓見底跡象）",
                1,
            )
        elif inflow_zone:
            return ("正常", f"資金流入本檔中，動能仍強（反向ETF CMF {cmf:.2f}）", 0)
        elif outflow_exhausted:
            return (
                "暫緩",
                f"資金流出動能趨緩（反向ETF CMF {cmf:.2f}，原型走強跡象）",
                -1,
            )
        elif outflow_zone:
            return ("正常", f"資金流出本檔中，尚未止穩（反向ETF CMF {cmf:.2f}）", 0)
        else:
            return ("正常", f"中性（CMF {cmf:.2f}）", 0)
    else:
        if outflow_exhausted:
            return (
                "加碼",
                f"資金流出後趨緩（CMF {cmf:.2f}，賣壓力竭跡象）",
                1,
            )
        elif outflow_zone:
            return ("正常", f"資金流出中，尚未止穩（CMF {cmf:.2f}）", 0)
        elif inflow_exhausted:
            return (
                "暫緩",
                f"資金流入動能趨緩（CMF {cmf:.2f}，追價風險仍在）",
                -1,
            )
        elif inflow_zone:
            return ("正常", f"資金持續流入中，動能仍強（CMF {cmf:.2f}）", 0)
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
    sign = -1 if is_inverse else 1
    lev, dd_strong, dd_mild, dd_near_high, ma60_low, ma60_high = _leverage_thresholds(
        leverage
    )

    momentum = pd.Series(0, index=df.index, dtype=int)
    momentum += sign * (df["RSI"] < RSI_OVERSOLD).astype(int)
    momentum -= sign * (df["RSI"] > RSI_OVERBOUGHT).astype(int)

    dd_near_high_mask = (df["Drawdown"] >= dd_near_high).astype(int)
    momentum += sign * (df["Drawdown"] <= dd_mild).astype(int)
    momentum += sign * (df["Drawdown"] <= dd_strong).astype(int)
    momentum -= sign * dd_near_high_mask
    if is_inverse:
        momentum += dd_near_high_mask

    ma60_slope = df["MA60"].diff(MA60_SLOPE_WINDOW)
    if is_inverse:
        momentum += ((df["MA60_Dev"] >= ma60_high) & (ma60_slope > 0)).astype(int)
        momentum -= (df["MA60_Dev"] <= ma60_low).astype(int)
    else:
        momentum += ((df["MA60_Dev"] <= ma60_low) & (ma60_slope > 0)).astype(int)
        momentum -= (df["MA60_Dev"] >= ma60_high).astype(int)

    cmf = df["CMF"]
    cmf_delta = cmf.diff(CMF_REVERSAL_WINDOW)
    price_delta = df["Close"].diff(CMF_REVERSAL_WINDOW)
    outflow_exhausted, inflow_exhausted = _cmf_exhaustion(cmf, cmf_delta, price_delta)
    cmf_pts = sign * (outflow_exhausted.astype(int) - inflow_exhausted.astype(int))

    return momentum.clip(-MOMENTUM_CAP, MOMENTUM_CAP) + cmf_pts * CMF_SCORE_WEIGHT


def compute_historical_buy_resonance(
    df: pd.DataFrame, is_inverse: bool = False, leverage: float = 1.0
) -> pd.Series:
    """向量化計算歷史每日「加碼」個別指標觸發數（0~4），供圖表標記較寬鬆的
    單一訊號買點使用。與 _buy_resonance 採用同一套個別指標定義（RSI / 距高點
    跌幅 / MA60 偏差 / CMF 是否各自判定為「加碼」），但不經過 compute_historical_scores
    的動能上限與 CMF 加權換算，直接計數原始指標數量，門檻較 compute_historical_scores
    寬鬆許多。is_inverse=True 時方向相反（反向型 ETF）。
    """
    lev, dd_strong, dd_mild, dd_near_high, ma60_low, ma60_high = _leverage_thresholds(
        leverage
    )
    ma60_slope = df["MA60"].diff(MA60_SLOPE_WINDOW)
    cmf = df["CMF"]
    cmf_delta = cmf.diff(CMF_REVERSAL_WINDOW)
    price_delta = df["Close"].diff(CMF_REVERSAL_WINDOW)
    outflow_exhausted, inflow_exhausted = _cmf_exhaustion(cmf, cmf_delta, price_delta)

    if is_inverse:
        rsi_buy = df["RSI"] > RSI_OVERBOUGHT
        dd_buy = df["Drawdown"] >= dd_near_high
        ma60_buy = (df["MA60_Dev"] >= ma60_high) & (ma60_slope > 0)
        cmf_buy = inflow_exhausted
    else:
        rsi_buy = df["RSI"] < RSI_OVERSOLD
        dd_buy = df["Drawdown"] <= dd_mild
        ma60_buy = (df["MA60_Dev"] <= ma60_low) & (ma60_slope > 0)
        cmf_buy = outflow_exhausted

    return (
        rsi_buy.astype(int)
        + dd_buy.astype(int)
        + ma60_buy.astype(int)
        + cmf_buy.astype(int)
    )
