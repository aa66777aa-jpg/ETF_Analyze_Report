import pandas as pd
import yfinance as yf

from config import (
    END_DATE,
    FETCH_START,
    HIGH_WINDOW,
    MA_PERIODS,
    MIN_TRADING_DAYS,
    RSI_PERIOD,
    START_DATE,
    W_PERIOD,
)


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

    df = df.dropna(subset=["RSI", "MA60", "MA120", "Drawdown"])

    if df.empty:
        print(f"⚠️  {stock_id} dropna 後無資料（歷史資料不足），跳過。")
        return None

    df.attrs["total_history_days"] = len(df)
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
