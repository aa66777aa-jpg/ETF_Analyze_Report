import glob
import os
from concurrent.futures import ThreadPoolExecutor

from analysis import analyze_stock
from chart import plot_stock
from config import OUTPUT_DIR, STOCK_LIST, _get_leverage, _is_index, _is_inverse
from report import generate_html_report
from signals import generate_index_context, generate_inverse_signal, generate_signal

if __name__ == "__main__":
    for f in glob.glob(os.path.join(OUTPUT_DIR, "*.png")):
        os.remove(f)

    with ThreadPoolExecutor(max_workers=4) as executor:
        dfs = list(executor.map(analyze_stock, STOCK_LIST))

    results = []
    for sid, df in zip(STOCK_LIST, dfs):
        if df is None:
            continue
        try:
            if _is_index(sid):
                signal_info = generate_index_context(df)
            elif _is_inverse(sid):
                signal_info = generate_inverse_signal(
                    df, sid, leverage=_get_leverage(sid)
                )
            else:
                signal_info = generate_signal(df, sid, leverage=_get_leverage(sid))
            b64 = plot_stock(sid, df, signal_info)
        except Exception as exc:
            print(f"❌ {sid} 訊號計算或繪圖發生未預期錯誤，已跳過：{exc}")
            continue
        results.append((sid, signal_info, b64))

    if results:
        generate_html_report(results)

    print(f"\n✅ 共成功儲存 {len(results)} / {len(STOCK_LIST)} 支股票的圖表。")
