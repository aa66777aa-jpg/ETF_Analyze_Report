import os
from datetime import date, timedelta

import yaml
import matplotlib
import matplotlib.font_manager as _fm

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

LOOKBACK_DAYS = 365
WARMUP_DAYS = 180
RSI_PERIOD = 14
CMF_PERIOD = 20  # CMF 慣例週期為 20（非跟隨 RSI 的 14），調整時需同步檢視下方 CMF 閾值
MIN_TRADING_DAYS = 120
MA_PERIODS = (20, 60, 120)
HIGH_WINDOW = 252

RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 70
DD_STRONG = -15
DD_MILD = -8
DD_NEAR_HIGH = -3
MA60_LOW = -5
MA60_HIGH = 8
CMF_OVERSOLD = -0.15
CMF_OVERBOUGHT = 0.15

TODAY = date.today().isoformat()
END_DATE = (date.today() + timedelta(days=1)).isoformat()
START_DATE = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
FETCH_START = (date.today() - timedelta(days=LOOKBACK_DAYS + WARMUP_DAYS)).isoformat()

_OVERALL_COLOR = {
    "積極加碼": "#e63946",
    "考慮加碼": "#f4a261",
    "觀望": "#888888",
    "考慮減碼": "#9b5de5",
    "積極減碼": "#6a0572",
}
_OVERALL_CLASS = {
    "積極加碼": "add-strong",
    "考慮加碼": "add",
    "觀望": "neutral",
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
