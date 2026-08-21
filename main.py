import glob
import os
from concurrent.futures import ThreadPoolExecutor

from analysis import analyze_stock
from chart import plot_stock
from config import OUTPUT_DIR, _get_leverage, _is_index, _is_inverse, parse_stock_input
from report import generate_html_report
from signals import generate_index_context, generate_inverse_signal, generate_signal

if __name__ == "__main__":
    stock_list = parse_stock_input()

    print(f"\n🔍 即將分析 {len(stock_list)} 支標的：{', '.join(stock_list)}")
    for sid in stock_list:
        tags = []
        if _is_index(sid):
            tags.append("指數")
        if _is_inverse(sid):
            tags.append("反向")
        if _get_leverage(sid) > 1:
            tags.append(f"{_get_leverage(sid):.0f}倍槓桿")
        if tags:
            print(f"   {sid} → {'、'.join(tags)}")

    for f in glob.glob(os.path.join(OUTPUT_DIR, "*.png")):
        os.remove(f)

    with ThreadPoolExecutor(max_workers=4) as executor:
        dfs = list(executor.map(analyze_stock, stock_list))

    results = []
    for sid, df in zip(stock_list, dfs):
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
        except Exception as exc:  # noqa: BLE001
            print(f"❌ {sid} 訊號計算或繪圖發生未預期錯誤，已跳過：{exc}")
            continue
        results.append((sid, signal_info, b64))

    if results:
        generate_html_report(results)

    print(f"\n✅ 共成功儲存 {len(results)} / {len(stock_list)} 支股票的圖表。")
