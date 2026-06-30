import os
from datetime import datetime, timedelta, timezone

from config import (
    _BASE,
    DOCS_DIR,
    LOOKBACK_DAYS,
    START_DATE,
    TODAY,
    _OVERALL_CLASS,
    _SIG_CLASS,
)


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

    sell_res = signal_info.get("sell_resonance", "—")
    sell_res_cls = signal_info.get("sell_resonance_cls", "neutral")

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
