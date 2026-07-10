import pandas as pd

from config import (
    CMF_OVERBOUGHT,
    CMF_OVERSOLD,
    DD_MILD,
    DD_NEAR_HIGH,
    HIGH_WINDOW,
    MA60_HIGH,
    MA60_LOW,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
)
from signal_common import (
    _buy_resonance,
    _classify_cmf,
    _combine_score,
    _holding_info,
    _leverage_thresholds,
    _score_to_overall,
    _sell_resonance,
)


def _dd_note(df: pd.DataFrame) -> str:
    total_days = df.attrs.get("total_history_days", len(df))
    return f"，高點視窗僅 {total_days} 日" if total_days < HIGH_WINDOW else ""


def _ma60_slope(df: pd.DataFrame) -> float:
    return float(df["MA60"].iloc[-1]) - float(df["MA60"].iloc[-21])


def generate_signal(
    df: pd.DataFrame, stock_id: str = "", leverage: float = 1.0
) -> dict:
    """根據最新一日數據判斷 ETF 定期投入的加碼時機。

    單項訊號（距高點跌幅最高 +2，其餘各項 -1 / 0 / +1）：
      +2 = 強力加碼訊號（距高點明顯回落，DD_STRONG）
      +1 = 加碼訊號（市場相對低估）
      -1 = 暫緩訊號（市場相對高估）
       0 = 正常

    綜合分數計算見 _combine_score（動能子分數與 CMF 各半權重相加）。

    綜合建議：
      score >= 3       → 積極加碼
      score == 2       → 考慮加碼
      -1 <= score <= 1 → 觀望
      score == -2      → 考慮減碼
      score <= -3      → 積極減碼

    最高分：+4（動能子分數 +2 ＋ CMF 資金流出力竭 +2）
    最低分：-4（動能子分數 -2 ＋ CMF 資金流入過熱力竭 -2）
    """
    latest = df.iloc[-1]
    price = float(latest["Close"])
    signals = {}

    lev, dd_strong, dd_mild, dd_near_high, ma60_low, ma60_high = _leverage_thresholds(
        leverage
    )
    lev_note = f"（{lev:.0f}倍槓桿調整）" if lev > 1 else ""

    rsi = float(latest["RSI"])
    if rsi < RSI_OVERSOLD:
        signals["rsi"] = ("加碼", f"超賣（RSI {rsi:.1f}）", 1)
    elif rsi > RSI_OVERBOUGHT:
        signals["rsi"] = ("暫緩", f"過熱（RSI {rsi:.1f}）", -1)
    else:
        signals["rsi"] = ("正常", f"中性（RSI {rsi:.1f}）", 0)

    drawdown = float(latest["Drawdown"])
    dd_note = _dd_note(df)
    if drawdown <= dd_strong:
        signals["drawdown"] = (
            "加碼",
            f"距高點 {drawdown:.1f}%（明顯回落{dd_note}{lev_note}）",
            2,
        )
    elif drawdown <= dd_mild:
        signals["drawdown"] = (
            "加碼",
            f"距高點 {drawdown:.1f}%（有所回落{dd_note}{lev_note}）",
            1,
        )
    elif drawdown >= dd_near_high:
        signals["drawdown"] = (
            "暫緩",
            f"距高點僅 {drawdown:.1f}%（接近高點{dd_note}{lev_note}）",
            -1,
        )
    else:
        signals["drawdown"] = ("正常", f"距高點 {drawdown:.1f}%{dd_note}", 0)

    ma60_dev = float(latest["MA60_Dev"])
    ma60_slope = _ma60_slope(df)
    if ma60_dev <= ma60_low:
        if ma60_slope > 0:
            signals["ma60"] = (
                "加碼",
                f"低於 MA60 {abs(ma60_dev):.1f}%（均線向上，回檔加碼{lev_note}）",
                1,
            )
        else:
            signals["ma60"] = (
                "正常",
                f"低於 MA60 {abs(ma60_dev):.1f}%（均線下彎，正常）",
                0,
            )
    elif ma60_dev >= ma60_high:
        signals["ma60"] = (
            "暫緩",
            f"高於 MA60 +{ma60_dev:.1f}%（過度延伸{lev_note}）",
            -1,
        )
    else:
        signals["ma60"] = ("正常", f"MA60 偏差 {ma60_dev:+.1f}%", 0)

    signals["cmf"] = _classify_cmf(df)

    score = _combine_score(signals)
    sell_resonance, sell_resonance_cls = _sell_resonance(signals)
    buy_resonance, buy_resonance_cls = _buy_resonance(signals)

    return {
        "signals": signals,
        "score": score,
        "overall": _score_to_overall(score),
        "price": price,
        "sell_resonance": sell_resonance,
        "sell_resonance_cls": sell_resonance_cls,
        "buy_resonance": buy_resonance,
        "buy_resonance_cls": buy_resonance_cls,
        "holding_info": _holding_info(stock_id, price),
        "is_inverse": False,
        "leverage": lev,
    }


def generate_index_context(df: pd.DataFrame) -> dict:
    """指數（^ 開頭）不給加碼建議，改輸出市場環境標籤供參考。"""
    latest = df.iloc[-1]
    rsi = float(latest["RSI"])
    drawdown = float(latest["Drawdown"])
    ma60_dev = float(latest["MA60_Dev"])
    cmf_raw = latest["CMF"]
    cmf_valid = pd.notna(cmf_raw)
    cmf = float(cmf_raw) if cmf_valid else 0.0

    bull = sum(
        [
            rsi > RSI_OVERBOUGHT,
            drawdown >= DD_NEAR_HIGH,
            ma60_dev > MA60_HIGH,
            cmf >= CMF_OVERBOUGHT,
        ]
    )
    bear = sum(
        [
            rsi < RSI_OVERSOLD,
            drawdown <= DD_MILD,
            ma60_dev < MA60_LOW,
            cmf <= CMF_OVERSOLD,
        ]
    )

    if bull >= 3:
        env, env_cls = "偏多", "wait"
    elif bear >= 3:
        env, env_cls = "偏空", "add"
    else:
        env, env_cls = "中性", "neutral"

    cmf_display = f"CMF {cmf:+.2f}" if cmf_valid else "CMF 資料不足"
    cmf_reason = f"CMF={cmf:.2f}" if cmf_valid else "CMF 成交量資料不足無法計算"

    return {
        "is_index": True,
        "is_inverse": False,
        "overall": f"市場環境：{env}",
        "overall_cls": env_cls,
        "score": 0,
        "price": float(latest["Close"]),
        "signals": {
            "rsi": (f"RSI {rsi:.0f}", f"RSI={rsi:.1f}", 0),
            "drawdown": (f"{drawdown:.1f}%", f"距高點跌幅={drawdown:.1f}%", 0),
            "ma60": (f"MA60 {ma60_dev:+.1f}%", f"MA60偏差={ma60_dev:.1f}%", 0),
            "cmf": (cmf_display, cmf_reason, 0),
        },
        "sell_resonance": "—",
        "sell_resonance_cls": "neutral",
        "buy_resonance": "—",
        "buy_resonance_cls": "neutral",
        "holding_info": {},
    }


def generate_inverse_signal(
    df: pd.DataFrame, stock_id: str = "", leverage: float = 1.0
) -> dict:
    """反向型 ETF 的評分邏輯：所有指標方向相反（市場過熱才是加碼時機）。

    RSI 超買 / CMF 資金流入過熱 / 接近52週高點 / 高於MA60 → 加碼
    RSI 超賣 / CMF 資金流出賣壓 / 大幅距離高點 / 低於MA60  → 暫緩
    leverage > 1 時（如 3 倍反向 SQQQ），DD / MA60 閾值等比放大。
    綜合分數計算與 generate_signal 相同，見 _combine_score。
    """
    latest = df.iloc[-1]
    price = float(latest["Close"])
    signals = {}

    lev, dd_strong, dd_mild, dd_near_high, ma60_low, ma60_high = _leverage_thresholds(
        leverage
    )
    lev_note = f"（{lev:.0f}倍槓桿調整）" if lev > 1 else ""

    rsi = float(latest["RSI"])
    if rsi > RSI_OVERBOUGHT:
        signals["rsi"] = ("加碼", f"市場超賣（反向ETF RSI {rsi:.1f}，過熱）", 1)
    elif rsi < RSI_OVERSOLD:
        signals["rsi"] = ("暫緩", f"市場大漲（反向ETF RSI {rsi:.1f}，超賣）", -1)
    else:
        signals["rsi"] = ("正常", f"中性（RSI {rsi:.1f}）", 0)

    drawdown = float(latest["Drawdown"])
    dd_note = _dd_note(df)
    if drawdown >= dd_near_high:
        signals["drawdown"] = (
            "加碼",
            f"距高點僅 {drawdown:.1f}%（接近高點，市場持續下跌{dd_note}{lev_note}）",
            2,
        )
    elif drawdown <= dd_strong:
        signals["drawdown"] = (
            "暫緩",
            f"距高點 {drawdown:.1f}%（大幅跌離，市場強勁反彈{dd_note}{lev_note}）",
            -2,
        )
    elif drawdown <= dd_mild:
        signals["drawdown"] = (
            "暫緩",
            f"距高點 {drawdown:.1f}%（有所跌離，市場反彈{dd_note}{lev_note}）",
            -1,
        )
    else:
        signals["drawdown"] = ("正常", f"距高點 {drawdown:.1f}%{dd_note}", 0)

    ma60_dev = float(latest["MA60_Dev"])
    ma60_slope = _ma60_slope(df)
    if ma60_dev >= ma60_high:
        if ma60_slope > 0:
            signals["ma60"] = (
                "加碼",
                f"高於MA60 +{ma60_dev:.1f}%（均線向上，市場下跌趨勢持續{lev_note}）",
                1,
            )
        else:
            signals["ma60"] = (
                "正常",
                f"高於MA60 +{ma60_dev:.1f}%（均線轉平，趨勢可能反轉）",
                0,
            )
    elif ma60_dev <= ma60_low:
        signals["ma60"] = (
            "暫緩",
            f"低於MA60 {abs(ma60_dev):.1f}%（市場上漲趨勢{lev_note}）",
            -1,
        )
    else:
        signals["ma60"] = ("正常", f"MA60 偏差 {ma60_dev:+.1f}%", 0)

    signals["cmf"] = _classify_cmf(df, inverse=True)

    score = _combine_score(signals)
    sell_resonance, sell_resonance_cls = _sell_resonance(signals)
    buy_resonance, buy_resonance_cls = _buy_resonance(signals)

    return {
        "signals": signals,
        "score": score,
        "overall": _score_to_overall(score),
        "price": price,
        "sell_resonance": sell_resonance,
        "sell_resonance_cls": sell_resonance_cls,
        "buy_resonance": buy_resonance,
        "buy_resonance_cls": buy_resonance_cls,
        "holding_info": _holding_info(stock_id, price),
        "is_inverse": True,
        "leverage": lev,
    }
