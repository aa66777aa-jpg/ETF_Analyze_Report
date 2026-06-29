import base64
import glob
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from io import BytesIO

import yaml

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
# 從 config.yaml 讀取設定
# ==========================================
_cfg_path = os.path.join(_BASE, "config.yaml")
try:
    with open(_cfg_path, encoding="utf-8") as _f:
        _cfg: dict = yaml.safe_load(_f) or {}
except FileNotFoundError:
    raise SystemExit(
        f"[ERROR] 找不到設定檔：{_cfg_path}\n請參考 README 建立 config.yaml。"
    )

STOCK_LIST: list[str] = _cfg.get("stock_list") or []
if not STOCK_LIST:
    raise SystemExit(
        "[ERROR] config.yaml 中 stock_list 為空或未設定，請至少填入一支股票代號。"
    )
_holdings_raw = _cfg.get("holdings")
HOLDINGS: dict[str, dict] = _holdings_raw if isinstance(_holdings_raw, dict) else {}
_inverse_raw = _cfg.get("inverse_list")
INVERSE_LIST: list[str] = _inverse_raw if isinstance(_inverse_raw, list) else []
_leverage_raw = _cfg.get("leverage_list")
LEVERAGE_MAP: dict[str, float] = (
    _leverage_raw if isinstance(_leverage_raw, dict) else {}
)

LOOKBACK_DAYS = 365  # 顯示的觀察天數
WARMUP_DAYS = 180  # 預先多抓的資料天數（確保 MA120 有足夠暖機）
RSI_PERIOD = 14  # RSI 回看天數
W_PERIOD = 14  # 威廉指標回看天數
MIN_TRADING_DAYS = 120  # 觀察區間最少交易日，不足則跳過
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
    "考慮減碼": "#9b5de5",
    "積極減碼": "#6a0572",
}
_OVERALL_CLASS = {
    "積極加碼": "add-strong",
    "考慮加碼": "add",
    "正常定期投入": "neutral",
    "謹慎觀察": "caution",
    "暫緩加碼": "wait",
    "考慮減碼": "sell",
    "積極減碼": "sell-strong",
}
_SIG_CLASS = {"加碼": "add", "暫緩": "wait", "正常": "neutral"}


def _safe_id(stock_id: str) -> str:
    return stock_id.replace("^", "").replace(".", "_")


def _is_index(stock_id: str) -> bool:
    return stock_id.startswith("^")


def _is_inverse(stock_id: str) -> bool:
    return stock_id in INVERSE_LIST


def _get_leverage(stock_id: str) -> float:
    return float(LEVERAGE_MAP.get(stock_id, 1.0))


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

    # --- 移動均線（min_periods=半週期，MA120 NaN 的資料列會在 dropna 時被過濾）---
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
    range_n = high_n - low_n
    # 區間小於收盤價 0.3%（或恰為零）時視為橫盤，設 NaN 避免誤判
    range_n = range_n.where(
        range_n / price.replace(0, float("nan")) >= 0.003, float("nan")
    )
    df["Williams_%R"] = ((high_n - price) / range_n) * -100

    # --- 成交量比率（相對 20 日均量）---
    df["Vol_MA20"] = df["Volume"].rolling(window=20, min_periods=5).mean()
    df["Vol_Ratio"] = (df["Volume"] / df["Vol_MA20"].replace(0, float("nan"))).fillna(
        1.0
    )

    # Williams_%R 橫盤時可為 NaN，不列入必要欄位
    # MA120 min_periods=60，成立未滿 60 個交易日的 ETF 在此被過濾
    df = df.dropna(subset=["RSI", "MA60", "MA120", "Drawdown"])

    if df.empty:
        print(f"⚠️  {stock_id} dropna 後無資料（歷史資料不足），跳過。")
        return None

    df.attrs["total_history_days"] = len(df)  # RSI/MA 計算後的有效交易日數
    df = df[df.index >= pd.Timestamp(START_DATE)]

    if df.empty:
        print(f"⚠️  {stock_id} 截回觀察區間後無資料，跳過。")
        return None

    if len(df) < MIN_TRADING_DAYS:
        print(
            f"⚠️  {stock_id} 觀察區間僅 {len(df)} 個交易日，不足 {MIN_TRADING_DAYS} 天，跳過。"
        )
        return None

    return df


def generate_signal(
    df: pd.DataFrame, stock_id: str = "", leverage: float = 1.0
) -> dict:
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
      score == -2 → 暫緩加碼
      score == -3 → 考慮減碼
      score <= -4 → 積極減碼

    最高分：+5（距高點明顯回落 +2，其餘三項均 +1）
    最低分：-4（四項指標均 -1）
    """
    total_days = df.attrs.get("total_history_days", len(df))
    latest = df.iloc[-1]
    price = float(latest["Close"])
    signals = {}

    # 槓桿調整：DD 與 MA60 閾值等比放大，RSI / W%R 為相對指標不調整
    lev = max(leverage, 1.0)
    dd_strong = DD_STRONG * lev
    dd_mild = DD_MILD * lev
    dd_near_high = DD_NEAR_HIGH * lev
    ma60_low = MA60_LOW * lev
    ma60_high = MA60_HIGH * lev
    lev_note = f"（{lev:.0f}倍槓桿調整）" if lev > 1 else ""

    # --- RSI ---
    rsi = float(latest["RSI"])
    if rsi < RSI_OVERSOLD:
        signals["rsi"] = ("加碼", f"超賣（RSI {rsi:.1f}）", 1)
    elif rsi > RSI_OVERBOUGHT:
        signals["rsi"] = ("暫緩", f"過熱（RSI {rsi:.1f}）", -1)
    else:
        signals["rsi"] = ("正常", f"中性（RSI {rsi:.1f}）", 0)

    # --- 距 52 週高點跌幅（高點視窗不足時加註說明） ---
    drawdown = float(latest["Drawdown"])
    dd_note = f"，高點視窗僅 {total_days} 日" if total_days < HIGH_WINDOW else ""
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

    # --- 價格 vs MA60（含斜率方向過濾） ---
    ma60_dev = float(latest["MA60_Dev"])
    ma60_slope = float(latest["MA60"]) - float(df["MA60"].iloc[-20])
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
                f"低於 MA60 {abs(ma60_dev):.1f}%（均線下彎，謹慎觀察）",
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

    # --- Williams %R（橫盤無波動時 NaN，視為中性） ---
    wr_raw = latest["Williams_%R"]
    if pd.isna(wr_raw):
        signals["williams"] = ("正常", "橫盤無波動（W%R 無法計算）", 0)
    else:
        wr = float(wr_raw)
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
    elif score == -2:
        overall = "暫緩加碼"
    elif score == -3:
        overall = "考慮減碼"
    else:
        overall = "積極減碼"

    # 賣點共振：同時發出暫緩訊號的指標數量
    sell_count = sum(1 for v in signals.values() if v[0] == "暫緩")
    if sell_count >= 3:
        sell_resonance, sell_resonance_cls = f"強力共振 ({sell_count}/4)", "sell-strong"
    elif sell_count >= 2:
        sell_resonance, sell_resonance_cls = f"共振 ({sell_count}/4)", "sell"
    elif sell_count == 1:
        sell_resonance, sell_resonance_cls = f"{sell_count}/4", "neutral"
    else:
        sell_resonance, sell_resonance_cls = "—", "neutral"

    # 持倉損益追蹤
    holding_info: dict = {}
    if stock_id and stock_id in HOLDINGS:
        h = HOLDINGS[stock_id]
        cost_raw = h.get("cost")
        if cost_raw is None:
            print(f"⚠️  HOLDINGS[{stock_id!r}] 缺少 cost 欄位，跳過持倉追蹤。")
        else:
            cost = float(cost_raw)
            target_pct = float(h.get("target_pct", 20))
            target_price = cost * (1 + target_pct / 100)
            pnl_pct = (price - cost) / cost * 100
            holding_info = {
                "cost": cost,
                "target_pct": target_pct,
                "target_price": target_price,
                "price": price,
                "pnl_pct": pnl_pct,
                "reached_target": price >= target_price,
            }

    return {
        "signals": signals,
        "score": score,
        "overall": overall,
        "price": price,
        "sell_resonance": sell_resonance,
        "sell_resonance_cls": sell_resonance_cls,
        "holding_info": holding_info,
        "leverage": lev,
    }


def generate_index_context(df: pd.DataFrame) -> dict:
    """指數（^ 開頭）不給加碼建議，改輸出市場環境標籤供參考。"""
    latest = df.iloc[-1]
    rsi = float(latest["RSI"])
    drawdown = float(latest["Drawdown"])
    ma60_dev = float(latest["MA60_Dev"])
    wr_raw = latest["Williams_%R"]
    wr = float(wr_raw) if not pd.isna(wr_raw) else -50.0  # NaN 時視為中性

    bull = sum([rsi > 60, drawdown >= DD_NEAR_HIGH, ma60_dev > 3, wr >= WR_OVERBOUGHT])
    bear = sum([rsi < 45, drawdown <= DD_MILD, ma60_dev < -3, wr <= WR_OVERSOLD])

    if bull >= 3:
        env, env_cls = "偏多", "wait"
    elif bear >= 3:
        env, env_cls = "偏空", "add"
    else:
        env, env_cls = "中性", "neutral"

    wr_display = f"W%R {wr:.0f}" if not pd.isna(wr_raw) else "W%R 橫盤"
    wr_reason = (
        f"Williams %R={wr:.1f}" if not pd.isna(wr_raw) else "Williams %R 橫盤無法計算"
    )

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
            "williams": (wr_display, wr_reason, 0),
        },
        "sell_resonance": "—",
        "sell_resonance_cls": "neutral",
        "holding_info": {},
    }


def generate_inverse_signal(
    df: pd.DataFrame, stock_id: str = "", leverage: float = 1.0
) -> dict:
    """反向型 ETF 的評分邏輯：所有指標方向相反（市場過熱才是加碼時機）。

    RSI 超買 / Williams %R 超買 / 接近52週高點 / 高於MA60 → 加碼
    RSI 超賣 / Williams %R 超賣 / 大幅距離高點 / 低於MA60  → 暫緩
    leverage > 1 時（如 3 倍反向 SQQQ），DD / MA60 閾值等比放大。
    """
    total_days = df.attrs.get("total_history_days", len(df))
    latest = df.iloc[-1]
    price = float(latest["Close"])
    signals = {}

    # 槓桿調整（反向槓桿 ETF 同樣需要縮放，RSI / W%R 不調整）
    lev = max(leverage, 1.0)
    dd_strong = DD_STRONG * lev
    dd_mild = DD_MILD * lev
    dd_near_high = DD_NEAR_HIGH * lev
    ma60_low = MA60_LOW * lev
    ma60_high = MA60_HIGH * lev
    lev_note = f"（{lev:.0f}倍槓桿調整）" if lev > 1 else ""

    # --- RSI（反向：超買才加碼，超賣才暫緩）---
    rsi = float(latest["RSI"])
    if rsi > RSI_OVERBOUGHT:
        signals["rsi"] = ("加碼", f"市場超賣（反向ETF RSI {rsi:.1f}，過熱）", 1)
    elif rsi < RSI_OVERSOLD:
        signals["rsi"] = ("暫緩", f"市場大漲（反向ETF RSI {rsi:.1f}，超賣）", -1)
    else:
        signals["rsi"] = ("正常", f"中性（RSI {rsi:.1f}）", 0)

    # --- 距 52 週高點（反向：接近高點 = 市場持續下跌 = +2；大幅跌離高點 = 市場反彈 = -2）---
    drawdown = float(latest["Drawdown"])
    dd_note = f"，高點視窗僅 {total_days} 日" if total_days < HIGH_WINDOW else ""
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

    # --- 價格 vs MA60（反向：高於MA60 = 市場下跌趨勢 = 利多）---
    ma60_dev = float(latest["MA60_Dev"])
    ma60_slope = float(latest["MA60"]) - float(df["MA60"].iloc[-20])
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

    # --- Williams %R（反向：超買才加碼，超賣才暫緩）---
    wr_raw = latest["Williams_%R"]
    if pd.isna(wr_raw):
        signals["williams"] = ("正常", "橫盤無波動（W%R 無法計算）", 0)
    else:
        wr = float(wr_raw)
        if wr >= WR_OVERBOUGHT:
            signals["williams"] = (
                "加碼",
                f"市場極度超賣（反向ETF W%R {wr:.1f}，超買）",
                1,
            )
        elif wr <= WR_OVERSOLD:
            signals["williams"] = (
                "暫緩",
                f"市場極度上漲（反向ETF W%R {wr:.1f}，超賣）",
                -1,
            )
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
    elif score == -2:
        overall = "暫緩加碼"
    elif score == -3:
        overall = "考慮減碼"
    else:
        overall = "積極減碼"

    sell_count = sum(1 for v in signals.values() if v[0] == "暫緩")
    if sell_count >= 3:
        sell_resonance, sell_resonance_cls = f"強力共振 ({sell_count}/4)", "sell-strong"
    elif sell_count >= 2:
        sell_resonance, sell_resonance_cls = f"共振 ({sell_count}/4)", "sell"
    elif sell_count == 1:
        sell_resonance, sell_resonance_cls = f"{sell_count}/4", "neutral"
    else:
        sell_resonance, sell_resonance_cls = "—", "neutral"

    holding_info: dict = {}
    if stock_id and stock_id in HOLDINGS:
        h = HOLDINGS[stock_id]
        cost_raw = h.get("cost")
        if cost_raw is None:
            print(f"⚠️  HOLDINGS[{stock_id!r}] 缺少 cost 欄位，跳過持倉追蹤。")
        else:
            cost = float(cost_raw)
            target_pct = float(h.get("target_pct", 20))
            target_price = cost * (1 + target_pct / 100)
            pnl_pct = (price - cost) / cost * 100
            holding_info = {
                "cost": cost,
                "target_pct": target_pct,
                "target_price": target_price,
                "price": price,
                "pnl_pct": pnl_pct,
                "reached_target": price >= target_price,
            }

    return {
        "signals": signals,
        "score": score,
        "overall": overall,
        "price": price,
        "sell_resonance": sell_resonance,
        "sell_resonance_cls": sell_resonance_cls,
        "holding_info": holding_info,
        "is_inverse": True,
        "leverage": lev,
    }


def compute_historical_scores(
    df: pd.DataFrame, is_inverse: bool = False, leverage: float = 1.0
) -> pd.Series:
    """向量化計算歷史每日評分，供圖表標記歷史買賣訊號使用。
    is_inverse=True 時，所有訊號方向相反（反向型 ETF）。
    leverage > 1 時，DD 與 MA60 閾值等比放大（槓桿型 ETF）。
    """
    scores = pd.Series(0, index=df.index, dtype=int)
    sign = -1 if is_inverse else 1
    lev = max(leverage, 1.0)
    dd_strong = DD_STRONG * lev
    dd_mild = DD_MILD * lev
    dd_near_high = DD_NEAR_HIGH * lev
    ma60_low = MA60_LOW * lev
    ma60_high = MA60_HIGH * lev

    scores += sign * (df["RSI"] < RSI_OVERSOLD).astype(int)
    scores -= sign * (df["RSI"] > RSI_OVERBOUGHT).astype(int)

    scores += sign * (df["Drawdown"] <= dd_mild).astype(int)
    scores += sign * (df["Drawdown"] <= dd_strong).astype(int)
    scores -= sign * (df["Drawdown"] >= dd_near_high).astype(int)
    # 反向 ETF：near-high 在 generate_inverse_signal 給 +2（與正向 strong 的疊加機制對稱）
    if is_inverse:
        scores += (df["Drawdown"] >= dd_near_high).astype(int)

    ma60_slope = df["MA60"].diff(20)
    if is_inverse:
        # 反向 ETF：高於 MA60 且均線向上才加碼；低於 MA60 則暫緩（不論斜率）
        scores += ((df["MA60_Dev"] >= ma60_high) & (ma60_slope > 0)).astype(int)
        scores -= (df["MA60_Dev"] <= ma60_low).astype(int)
    else:
        # 正向 ETF：低於 MA60 且均線向上才加碼；高於 MA60 則暫緩（不論斜率）
        scores += ((df["MA60_Dev"] <= ma60_low) & (ma60_slope > 0)).astype(int)
        scores -= (df["MA60_Dev"] >= ma60_high).astype(int)

    wr = df["Williams_%R"].fillna(-50)
    scores += sign * (wr <= WR_OVERSOLD).astype(int)
    scores -= sign * (wr >= WR_OVERBOUGHT).astype(int)

    return scores


def plot_stock(stock_id: str, df: pd.DataFrame, signal_info: dict) -> str:
    """繪製四格子圖（均線+量 / RSI / Williams %R / 距高點跌幅）並存檔。"""
    overall = signal_info["overall"]
    score = signal_info["score"]
    last_price = signal_info["price"]
    is_index = signal_info.get("is_index", False)
    is_inverse = signal_info.get("is_inverse", False)
    leverage = signal_info.get("leverage", 1.0)
    ann_color = _OVERALL_COLOR.get(overall, "#888888")

    # 縮放後的圖四閾值（讓虛線位置與評分邏輯一致）
    lev = max(leverage, 1.0)
    plot_dd_strong = DD_STRONG * lev
    plot_dd_mild = DD_MILD * lev
    plot_dd_near_high = DD_NEAR_HIGH * lev

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
    # ── 歷史買賣訊號標記 ─────────────────────────────
    h_scores = compute_historical_scores(df, is_inverse=is_inverse, leverage=leverage)
    buy_idx = h_scores[h_scores >= 2].index
    sell_idx = h_scores[h_scores <= -2].index
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

    # ── 持倉成本與停利目標線 ────────────────────────
    if stock_id in HOLDINGS:
        _h = HOLDINGS[stock_id]
        _cost_raw = _h.get("cost")
        if _cost_raw is not None:
            _cost = float(_cost_raw)
            _tgt_pct = float(_h.get("target_pct", 20))
            _tgt_price = _cost * (1 + _tgt_pct / 100)
            ax1.axhline(
                _cost,
                color="#f4a261",
                linestyle="-.",
                linewidth=1.5,
                label=f"持倉成本 {_cost:.2f}",
                alpha=0.85,
            )
            ax1.axhline(
                _tgt_price,
                color="#9b5de5",
                linestyle="-.",
                linewidth=1.5,
                label=f"停利目標 {_tgt_price:.2f} (+{_tgt_pct:.0f}%)",
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
    dd = df["Drawdown"]
    ax4.plot(df.index, dd, color="#264653", linewidth=1.2, label="距高點跌幅")
    if is_inverse:
        # 反向 ETF：接近高點 = 市場持續下跌 = 利多（紅）；跌離高點 = 市場反彈 = 警示（綠）
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


def _build_stock_html(
    stock_id: str, signal_info: dict, img_b64: str = ""
) -> tuple[str, str]:
    """回傳 (summary_row_html, chart_card_html)。"""
    overall = signal_info["overall"]
    score = signal_info["score"]
    signals = signal_info["signals"]
    is_index = signal_info.get("is_index", False)
    is_inverse = signal_info.get("is_inverse", False)

    if is_index:
        overall_cls = signal_info.get("overall_cls", "neutral")
    else:
        overall_cls = _OVERALL_CLASS.get(overall, "neutral")

    img_tag = ""
    if img_b64:
        img_tag = f'<img src="data:image/png;base64,{img_b64}" alt="{stock_id}" loading="lazy">'

    # 賣點共振欄位
    sell_res = signal_info.get("sell_resonance", "—")
    sell_res_cls = signal_info.get("sell_resonance_cls", "neutral")

    # 持倉損益欄位
    holding_info = signal_info.get("holding_info", {})
    if holding_info:
        pnl = holding_info["pnl_pct"]
        pnl_cls = "pnl-pos" if pnl >= 0 else "pnl-neg"
        if holding_info["reached_target"]:
            target_td = '<td class="pnl-target">已達停利 ✓</td>'
        else:
            remaining = (holding_info["target_price"] / holding_info["price"] - 1) * 100
            target_td = f'<td class="neutral">尚差 {remaining:.1f}%</td>'
        holding_tds = f'<td class="{pnl_cls}">{pnl:+.1f}%</td>{target_td}'
    else:
        holding_tds = '<td class="neutral">—</td><td class="neutral">—</td>'

    # card meta bar（賣點共振 + 持倉損益）
    meta_parts = []
    if sell_res != "—":
        meta_parts.append(f'賣點共振：<span class="{sell_res_cls}">{sell_res}</span>')
    if holding_info:
        pnl_m = holding_info["pnl_pct"]
        pnl_cls_m = "pnl-pos" if pnl_m >= 0 else "pnl-neg"
        meta_parts.append(f'持倉損益：<span class="{pnl_cls_m}">{pnl_m:+.1f}%</span>')
        if holding_info["reached_target"]:
            meta_parts.append('<span class="pnl-target">已達停利目標 ✓</span>')
    meta_html = (
        f'<div class="card-meta">{" &nbsp;·&nbsp; ".join(meta_parts)}</div>'
        if meta_parts
        else ""
    )

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
            f'<td class="neutral">—</td>'
            f'<td class="neutral">—</td>'
            f'<td class="neutral">—</td>'
            f"</tr>"
        )
    else:

        def sig_td(key: str) -> str:
            sig, reason, _ = signals[key]
            cls = _SIG_CLASS.get(sig, "neutral")
            return f'<td class="{cls}" title="{reason}">{sig}</td>'

        score_suffix = f"&nbsp;({score:+d})"
        inverse_badge = ' <span class="inverse-badge">反向</span>' if is_inverse else ""
        row = (
            f"<tr>"
            f'<td class="sid">{stock_id}{inverse_badge}</td>'
            f'<td class="{overall_cls} overall">{overall}{score_suffix}</td>'
            f"{sig_td('rsi')}"
            f"{sig_td('drawdown')}"
            f"{sig_td('ma60')}"
            f"{sig_td('williams')}"
            f'<td class="{sell_res_cls}">{sell_res}</td>'
            f"{holding_tds}"
            f"</tr>"
        )

    card = (
        f'<div class="card">'
        f'<div class="card-header">'
        f'<span class="sid">{stock_id}</span>'
        f'<span class="sig {overall_cls}">{overall}</span>'
        f"</div>"
        f"{meta_html}"
        f"{img_tag}"
        f"</div>"
    )
    return row, card


def generate_html_report(results: list[tuple[str, dict, str]]):
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

    # 將外部 CSS 內嵌，確保 docs/index.html 自包含
    css_path = os.path.join(_BASE, "report.css")
    if os.path.exists(css_path):
        with open(css_path, encoding="utf-8") as f:
            css_content = f.read()
        template = template.replace(
            '<link rel="stylesheet" href="report.css">',
            f"<style>\n{css_content}\n</style>",
        )

    rows, cards = zip(*[_build_stock_html(sid, sig, b64) for sid, sig, b64 in results])

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
    for f in glob.glob(os.path.join(OUTPUT_DIR, "*.png")):
        os.remove(f)

    with ThreadPoolExecutor(max_workers=4) as executor:
        dfs = list(executor.map(analyze_stock, STOCK_LIST))

    results = []
    for sid, df in zip(STOCK_LIST, dfs):
        if df is not None:
            if _is_index(sid):
                signal_info = generate_index_context(df)
            elif _is_inverse(sid):
                signal_info = generate_inverse_signal(
                    df, sid, leverage=_get_leverage(sid)
                )
            else:
                signal_info = generate_signal(df, sid, leverage=_get_leverage(sid))
            b64 = plot_stock(sid, df, signal_info)
            results.append((sid, signal_info, b64))

    if results:
        generate_html_report(results)

    print(f"\n✅ 共成功儲存 {len(results)} / {len(STOCK_LIST)} 支股票的圖表。")
