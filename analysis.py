import pandas as pd
import yfinance as yf

from config import (
    CMF_PERIOD,
    END_DATE,
    FETCH_START,
    HIGH_WINDOW,
    MA_PERIODS,
    MIN_TRADING_DAYS,
    RSI_PERIOD,
    START_DATE,
)


# Yahoo Finance 對部分台股（尤其常態分割的槓桿型 ETF）偶爾未正確反映股票分割，
# 導致收盤價序列出現單日暴漲暴跌的假跳空，使距高點跌幅、MA 偏差、RSI 等指標
# 全部失真，可能誤判為「積極加碼」。台股單日漲跌幅上限為 10%，因此正常交易日
# 不可能出現超過此倍數的單日價格跳動，一旦出現即視為資料異常。
_SPLIT_JUMP_RATIO = 1.8


def analyze_stock(stock_id: str):
    """下載並計算單支股票的技術指標，回傳 DataFrame；若資料不足或發生錯誤則回傳 None。"""
    try:
        return _analyze_stock_impl(stock_id)
    except Exception as exc:
        print(f"❌ {stock_id} 發生未預期錯誤，已跳過：{exc}")
        return None


def _has_unadjusted_split(price: pd.Series) -> bool:
    ratio = (price / price.shift(1)).dropna()
    return bool(((ratio >= _SPLIT_JUMP_RATIO) | (ratio <= 1 / _SPLIT_JUMP_RATIO)).any())


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

    if _has_unadjusted_split(price):
        print(
            f"⚠️  {stock_id} 偵測到單日價格跳動超過 "
            f"{(_SPLIT_JUMP_RATIO - 1) * 100:.0f}%，疑似股票分割未被 Yahoo Finance "
            "正確調整，資料不可信，已跳過。"
        )
        return None

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

    # --- 量比（當日量相對 20 日均量的倍數）---
    df["Vol_Ratio"] = (
        df["Volume"] / df["Volume"].rolling(window=MA_PERIODS[0], min_periods=10).mean()
    )

    # --- CMF (Chaikin Money Flow)：資金流量指標 ---
    # 當日高低差 < 收盤價 0.3%（含 High/Low 缺值）視為橫盤或資料異常，
    # 該日成交量自分子分母一併剔除，避免稀釋 20 日資金流量指標
    hl_range = df["High"] - df["Low"]
    flat_day = (hl_range.abs() < price * 0.003) | hl_range.isna()
    mfm = ((price - df["Low"]) - (df["High"] - price)) / hl_range
    mfm = mfm.mask(flat_day, 0).replace([float("inf"), float("-inf")], 0).fillna(0)
    cmf_volume = df["Volume"].mask(flat_day, 0)
    mfv = mfm * cmf_volume
    df["CMF"] = (
        mfv.rolling(window=CMF_PERIOD).sum()
        / cmf_volume.rolling(window=CMF_PERIOD).sum()
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
