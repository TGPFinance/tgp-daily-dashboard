import os
import json
import requests
from pathlib import Path
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor

SUPERMETRICS_API_KEY = os.environ["SUPERMETRICS_API_KEY"]

TODAY        = date.today()
YESTERDAY    = TODAY - timedelta(days=1)
DATE_STR     = YESTERDAY.strftime("%Y-%m-%d")
DISPLAY_DATE = YESTERDAY.strftime("%B %d, %Y")
PY_DATE_STR  = (YESTERDAY - timedelta(days=365)).strftime("%Y-%m-%d")
PY_DISPLAY   = (YESTERDAY - timedelta(days=365)).strftime("%Y")

T30_START_DT = YESTERDAY - timedelta(days=29)
T30_START    = T30_START_DT.strftime("%Y-%m-%d")
T30_END      = DATE_STR
T30_LABEL    = f"{T30_START_DT.strftime('%b %d')} – {YESTERDAY.strftime('%b %d, %Y')}"

SM_BASE = "https://api.supermetrics.com/enterprise/v2/query/data/json"
CACHE_FILE = "data_cache.json"

# Brand
BRAND_COLOR = "#2c4ea2"
BRAND_COLOR_DARK = "#1e3a7a"
LOGO_PATH = "TGP-Logo-White.png"

ICONS = {
    'amazon':  'https://cdn.jsdelivr.net/npm/simple-icons@v11/icons/amazon.svg',
    'shopify': 'https://cdn.jsdelivr.net/npm/simple-icons@v11/icons/shopify.svg',
    'meta':    'https://cdn.jsdelivr.net/npm/simple-icons@v11/icons/meta.svg',
    'google':  'https://cdn.jsdelivr.net/npm/simple-icons@v11/icons/googleads.svg',
    'klaviyo': 'https://cdn.jsdelivr.net/npm/feather-icons@4.29.2/dist/icons/mail.svg',
}

ACCOUNTS = {
    "amazon_seller": "ATVPDKIKX0DER",
    "amazon_ads":    "1221224134439971",
    "meta":          "act_898245987330933",
    "google_ads":    "9578659454",
    "klaviyo":       "the good patch",
    "shopify":       "gid://shopify/Shop/5489557622",
}

SOURCES = {
    'amazon_seller': {
        'ds_id': 'ASELL', 'account_key': 'amazon_seller',
        'fields': 'ordered_product_sales,units_ordered,sessions,unit_session_percentage,page_views',
        'extra_params': {'report_type': 'sales_and_traffic_by_date'},
        'timeout': 300,
    },
    'amazon_ads': {
        'ds_id': 'AA', 'account_key': 'amazon_ads',
        'fields': 'cost,attributedSales14d,clicks,impressions',
        'extra_params': {'report_type': 'SponsoredProduct'},
        'timeout': 300,
    },
    'shopify': {
        'ds_id': 'SHP', 'account_key': 'shopify',
        'fields': 'gross_sales,sm_order_count,net_sales,net_quantity',
        'extra_params': {'report_type': 'Order'},
        'timeout': 180,
    },
    'meta': {
        'ds_id': 'FA', 'account_key': 'meta',
        'fields': 'spend,purchase_value,clicks,impressions',
        'extra_params': None,
        'timeout': 180,
    },
    'google_ads': {
        'ds_id': 'AW', 'account_key': 'google_ads',
        'fields': 'cost,conversions_value,clicks,impressions',
        'extra_params': None,
        'timeout': 180,
    },
    'klaviyo_email': {
        'ds_id': 'KLAV', 'account_key': 'klaviyo',
        'fields': 'klaviyo_total_recipients,klaviyo_received_email,klaviyo_opened_email_unique,klaviyo_clicked_email_unique',
        'extra_params': {'report_type': 'MetricExportDaily'},
        'timeout': 180,
    },
    'klaviyo_attr': {
        'ds_id': 'KLAV', 'account_key': 'klaviyo',
        'fields': 'shopify_placed_order,shopify_placed_order_value',
        'extra_params': {'report_type': 'MetricExportAttributedCampaignDaily'},
        'timeout': 180,
    },
}

def load_cache():
    try: return json.loads(Path(CACHE_FILE).read_text())
    except: return {}

def save_cache(c):
    Path(CACHE_FILE).write_text(json.dumps(c, indent=2, default=str))

cache = load_cache()
cache.setdefault('daily', {})
cache_warnings = []

def to_float(v):
    try: return float(v)
    except: return 0

def safe_div(numer, denom):
    try:
        n, d = float(numer), float(denom)
        return n / d if d > 0 else None
    except: return None

def sm_fetch_rows(ds_id, account_id, fields, start_date, end_date, extra_params=None, timeout=180, retries=1):
    params = {"api_key": SUPERMETRICS_API_KEY, "ds_id": ds_id, "ds_accounts": account_id,
              "date_range_type": "custom", "start_date": start_date, "end_date": end_date, "fields": fields}
    if extra_params: params.update(extra_params)
    for attempt in range(retries + 1):
        try:
            r = requests.get(SM_BASE, params=params, timeout=timeout)
            r.raise_for_status()
            rows = r.json().get("data", [])
            fl = fields.split(",")
            return [dict(zip(fl, row)) for row in rows[1:]] if len(rows) >= 2 else []
        except (requests.Timeout, requests.ConnectionError):
            if attempt < retries:
                print(f"  {ds_id} timed out (attempt {attempt+1}), retrying...")
                continue
            print(f"  Warning: {ds_id} ({start_date}→{end_date}) timeout after retries")
            return []
        except Exception as e:
            print(f"  Warning: {ds_id} ({start_date}→{end_date}) failed — {e}")
            return []

def all_30d_dates():
    return [(YESTERDAY - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(30)]

def ensure_30d_cache(source_key):
    cfg = SOURCES[source_key]
    daily = cache['daily'].setdefault(source_key, {})
    needed = [d for d in all_30d_dates() if d not in daily]
    if not needed:
        return
    start, end = min(needed), max(needed)
    fields = f"date,{cfg['fields']}"
    print(f"  Fetching {source_key}: {len(needed)} days ({start}→{end})")
    rows = sm_fetch_rows(cfg['ds_id'], ACCOUNTS[cfg['account_key']],
                         fields, start, end,
                         extra_params=cfg.get('extra_params'),
                         timeout=cfg.get('timeout', 180))
    if rows:
        for row in rows:
            d = row.get('date')
            if d:
                daily[d] = {k: v for k, v in row.items() if k != 'date'}
        return
    if DATE_STR in needed:
        print(f"  {source_key}: range fetch failed, trying yesterday only")
        rows = sm_fetch_rows(cfg['ds_id'], ACCOUNTS[cfg['account_key']],
                             fields, DATE_STR, DATE_STR,
                             extra_params=cfg.get('extra_params'),
                             timeout=cfg.get('timeout', 180))
        if rows:
            for row in rows:
                d = row.get('date')
                if d:
                    daily[d] = {k: v for k, v in row.items() if k != 'date'}
            return
    cache_warnings.append(f"{source_key} (cached: {len(daily)}/30 days)")

def ensure_py(source_key):
    py_key = f"py_{source_key}_{PY_DATE_STR}"
    if py_key in cache:
        return
    cfg = SOURCES[source_key]
    rows = sm_fetch_rows(cfg['ds_id'], ACCOUNTS[cfg['account_key']],
                         f"date,{cfg['fields']}", PY_DATE_STR, PY_DATE_STR,
                         extra_params=cfg.get('extra_params'),
                         timeout=cfg.get('timeout', 180))
    if rows:
        cache[py_key] = {k: v for k, v in rows[0].items() if k != 'date'}

def ensure_top_products():
    rows = sm_fetch_rows("ASELL", ACCOUNTS["amazon_seller"],
                         "title,ordered_product_sales,units_ordered",
                         T30_START, T30_END,
                         extra_params={"report_type": "sales_and_traffic_by_asin"},
                         timeout=300)
    if rows:
        cache['top_products'] = {"data": rows, "date": DATE_STR}
    elif 'top_products' in cache:
        cache_warnings.append(f"top_products (from {cache['top_products'].get('date','?')})")

def ensure_campaigns():
    em = sm_fetch_rows("KLAV", ACCOUNTS["klaviyo"],
        "campaign_name,campaign_subject,campaign_send_date,klaviyo_total_recipients,klaviyo_open_rate,klaviyo_click_rate",
        T30_START, T30_END,
        extra_params={"report_type": "MetricExportCampaign"}, timeout=300)
    attr = sm_fetch_rows("KLAV", ACCOUNTS["klaviyo"],
        "campaign_name,shopify_placed_order,shopify_placed_order_value",
        T30_START, T30_END,
        extra_params={"report_type": "MetricExportAttributedCampaign"}, timeout=300)
    if em:
        cache['campaigns'] = {"email": em, "attr": attr, "date": DATE_STR}
    elif 'campaigns' in cache:
        cache_warnings.append(f"campaigns (from {cache['campaigns'].get('date','?')})")

print(f"Updating cache for {DISPLAY_DATE}...")

with ThreadPoolExecutor(max_workers=14) as ex:
    futs = []
    for src in SOURCES:
        futs.append(ex.submit(ensure_30d_cache, src))
    for src in ['amazon_seller', 'shopify']:
        futs.append(ex.submit(ensure_py, src))
    futs.append(ex.submit(ensure_top_products))
    futs.append(ex.submit(ensure_campaigns))
    for f in futs:
        f.result()

save_cache(cache)

def day(src, d=DATE_STR):
    return cache['daily'].get(src, {}).get(d, {})

def sum_field(src, field, days=30):
    daily = cache['daily'].get(src, {})
    total = 0
    for d in range(days):
        date_str = (YESTERDAY - timedelta(days=d)).strftime("%Y-%m-%d")
        total += to_float(daily.get(date_str, {}).get(field, 0))
    return total

def daily_series(src, field, days=30):
    daily = cache['daily'].get(src, {})
    series = []
    for d in range(days - 1, -1, -1):
        date_str = (YESTERDAY - timedelta(days=d)).strftime("%Y-%m-%d")
        series.append((date_str, to_float(daily.get(date_str, {}).get(field, 0))))
    return series

amazon_seller = day('amazon_seller')
amazon_ads    = day('amazon_ads')
shopify       = day('shopify')
meta          = day('meta')
google_ads    = day('google_ads')
klaviyo_email = day('klaviyo_email')
klaviyo_attr  = day('klaviyo_attr')

amazon_seller_py = cache.get(f"py_amazon_seller_{PY_DATE_STR}", {})
shopify_py       = cache.get(f"py_shopify_{PY_DATE_STR}", {})

amazon_ads['roas'] = safe_div(amazon_ads.get('attributedSales14d'), amazon_ads.get('cost'))
amazon_ads['acos'] = safe_div(amazon_ads.get('cost'), amazon_ads.get('attributedSales14d'))
meta['roas'] = safe_div(meta.get('purchase_value'), meta.get('spend'))
meta['cpc']  = safe_div(meta.get('spend'), meta.get('clicks'))
meta['ctr']  = safe_div(meta.get('clicks'), meta.get('impressions'))
google_ads['roas'] = safe_div(google_ads.get('conversions_value'), google_ads.get('cost'))
google_ads['cpc']  = safe_div(google_ads.get('cost'), google_ads.get('clicks'))
google_ads['ctr']  = safe_div(google_ads.get('clicks'), google_ads.get('impressions'))

klav_open  = safe_div(klaviyo_email.get('klaviyo_opened_email_unique'),  klaviyo_email.get('klaviyo_received_email'))
klav_click = safe_div(klaviyo_email.get('klaviyo_clicked_email_unique'), klaviyo_email.get('klaviyo_received_email'))

amazon_aov_val    = safe_div(amazon_seller.get('ordered_product_sales'), amazon_seller.get('units_ordered'))
amazon_aov_py_val = safe_div(amazon_seller_py.get('ordered_product_sales'), amazon_seller_py.get('units_ordered'))
shopify_aov_val   = safe_div(shopify.get('net_sales'), shopify.get('sm_order_count'))
shopify_aov_py_val = safe_div(shopify_py.get('net_sales'), shopify_py.get('sm_order_count'))
shopify_per_unit_val = safe_div(shopify.get('net_sales'), shopify.get('net_quantity'))

amzs_rev_30  = sum_field('amazon_seller', 'ordered_product_sales')
amzs_unit_30 = sum_field('amazon_seller', 'units_ordered')
amzs_sess_30 = sum_field('amazon_seller', 'sessions')
amzs_cvr_30  = safe_div(amzs_unit_30, amzs_sess_30)

amza_cost_30  = sum_field('amazon_ads', 'cost')
amza_sales_30 = sum_field('amazon_ads', 'attributedSales14d')
amza_roas_30  = safe_div(amza_sales_30, amza_cost_30)
amza_acos_30  = safe_div(amza_cost_30, amza_sales_30)

shop_net_30   = sum_field('shopify', 'net_sales')
shop_ord_30   = sum_field('shopify', 'sm_order_count')
shop_qty_30   = sum_field('shopify', 'net_quantity')
shop_aov_30   = safe_div(shop_net_30, shop_ord_30)
shop_pu_30    = safe_div(shop_net_30, shop_qty_30)

meta_spend_30 = sum_field('meta', 'spend')
meta_pv_30    = sum_field('meta', 'purchase_value')
meta_roas_30  = safe_div(meta_pv_30, meta_spend_30)

g_spend_30 = sum_field('google_ads', 'cost')
g_cv_30    = sum_field('google_ads', 'conversions_value')
g_roas_30  = safe_div(g_cv_30, g_spend_30)

amazon_daily_series  = daily_series('amazon_seller', 'ordered_product_sales')
amazon_sess_series   = daily_series('amazon_seller', 'sessions')
amazon_cvr_series    = []
for d_str, _ in amazon_daily_series:
    row = cache['daily'].get('amazon_seller', {}).get(d_str, {})
    cvr = to_float(row.get('unit_session_percentage', 0))
    if 0 < cvr < 1: cvr *= 100
    amazon_cvr_series.append((d_str, cvr))

shopify_chart_raw = [(d, v) for d, v in daily_series('shopify', 'net_sales') if v > 0]
if len(shopify_chart_raw) > 1:
    shopify_chart_raw = shopify_chart_raw[:-1]

amazon_products = sorted(cache.get('top_products', {}).get('data', []),
                         key=lambda r: to_float(r.get('ordered_product_sales')), reverse=True)[:5]

camp_data = cache.get('campaigns', {})
camp_email = camp_data.get('email', [])
camp_attr = {c.get('campaign_name'): c for c in camp_data.get('attr', [])}
for c in camp_email:
    a = camp_attr.get(c.get('campaign_name'), {})
    c['shopify_placed_order'] = a.get('shopify_placed_order')
    c['shopify_placed_order_value'] = a.get('shopify_placed_order_value')
klaviyo_campaigns = sorted(camp_email, key=lambda c: c.get('campaign_send_date', ''), reverse=True)[:5]

print(f"  Days cached: amazon_seller={len(cache['daily'].get('amazon_seller',{}))}, amazon_ads={len(cache['daily'].get('amazon_ads',{}))}, shopify={len(cache['daily'].get('shopify',{}))}")
if cache_warnings:
    print(f"  Cache fallbacks: {cache_warnings}")

def fmt_money(v, big=False):
    if v in (None, '', 0): return "—"
    try:
        n = float(v)
        return f"${n/1000:,.1f}K" if big and n >= 1000 else f"${n:,.2f}"
    except: return "—"

def fmt_num(v, big=False):
    if v in (None, '', 0): return "—"
    try:
        n = float(v)
        return f"{n/1000:,.1f}K" if big and n >= 1000 else (f"{n:,.0f}" if n >= 1 else f"{n:g}")
    except: return str(v)

def fmt_pct(v):
    if v in (None, ''): return "—"
    try:
        n = float(v)
        if n == 0: return "—"
        if abs(n) < 1: n *= 100
        return f"{n:,.2f}%"
    except: return "—"

def fmt_roas(v):
    if v in (None, '', 0): return "—"
    try: return f"{float(v):,.2f}×"
    except: return "—"

def yoy_badge(cur, prior, fmt=fmt_money):
    if cur in (None, '', 0) or prior in (None, '', 0): return ""
    try:
        c, p = float(cur), float(prior)
        if p == 0: return ""
        pct = ((c - p) / p) * 100
        color = "#22c55e" if pct >= 0 else "#ef4444"
        sign = "+" if pct >= 0 else ""
        return f'<div class="sub">vs {fmt(prior)} ({PY_DISPLAY}) <span style="color:{color};font-weight:500">{sign}{pct:.1f}% YoY</span></div>'
    except: return ""

def card(value, label, sub=""):
    return f'<div class="card"><div class="label">{label}</div><div class="value">{value}</div>{sub}</div>'

def section_title(icon_key, title, badge=''):
    icon = f'<img class="channel-icon" src="{ICONS[icon_key]}" alt="" />' if icon_key else ''
    badge_html = f'<span class="badge">{badge}</span>' if badge else ''
    return f'<div class="section-title">{icon}<h2>{title}</h2>{badge_html}</div>'

def rolling_avg(values, window=7):
    out = []
    for i in range(len(values)):
        s = max(0, i - window + 1)
        sl = [v for v in values[s:i+1] if v is not None]
        out.append(round(sum(sl)/len(sl), 2) if sl else 0)
    return out

def product_rows():
    top_total = sum(to_float(p.get('ordered_product_sales')) for p in amazon_products) or 1
    out = ""
    for p in amazon_products:
        rev = to_float(p.get('ordered_product_sales'))
        units = to_float(p.get('units_ordered'))
        share = (rev / top_total) * 100
        title = (p.get('title') or 'Unknown')[:60]
        out += f"""
        <tr>
          <td class="prod-name">{title}</td>
          <td class="prod-num">${rev:,.0f}</td>
          <td class="prod-num">{units:,.0f}</td>
          <td class="prod-bar"><div class="bar-wrap"><div class="bar-fill" style="width:{share:.1f}%"></div></div></td>
        </tr>"""
    return out

def campaign_rows():
    out = ""
    for c in klaviyo_campaigns:
        name = (c.get('campaign_name') or 'Unnamed')[:40]
        subject = (c.get('campaign_subject') or '—')[:50]
        send_date = c.get('campaign_send_date', '—')
        recipients = fmt_num(c.get('klaviyo_total_recipients'))
        open_rate = fmt_pct(c.get('klaviyo_open_rate'))
        click_rate = fmt_pct(c.get('klaviyo_click_rate'))
        rev = fmt_money(c.get('shopify_placed_order_value'))
        orders = fmt_num(c.get('shopify_placed_order'))
        out += f"""
        <tr>
          <td><div class="prod-name">{name}</div><div class="sub">{subject}</div></td>
          <td class="prod-num">{send_date}</td>
          <td class="prod-num">{recipients}</td>
          <td class="prod-num">{open_rate}</td>
          <td class="prod-num">{click_rate}</td>
          <td class="prod-num">{rev}</td>
          <td class="prod-num">{orders}</td>
        </tr>"""
    return out

amazon_chart_labels = [d for d, _ in amazon_daily_series]
amazon_chart_values = [v for _, v in amazon_daily_series]
amazon_chart_avg7   = rolling_avg(amazon_chart_values, 7)
amazon_sess_values  = [v for _, v in amazon_sess_series]
amazon_cvr_values   = [v for _, v in amazon_cvr_series]
shopify_chart_labels = [d for d, _ in shopify_chart_raw]
shopify_chart_values = [v for _, v in shopify_chart_raw]
shopify_chart_avg7   = rolling_avg(shopify_chart_values, 7)

def revenue_chart_js(canvas_id, labels, values, avg, label_name='Daily revenue'):
    return f"""new Chart(document.getElementById('{canvas_id}'), {{
      type: 'bar',
      data: {{ labels: {json.dumps(labels)}, datasets: [
        {{ label: '{label_name}', data: {json.dumps(values)}, backgroundColor: 'rgba(44, 78, 162, 0.7)', borderRadius: 2 }},
        {{ label: '7-day avg', type: 'line', data: {json.dumps(avg)}, borderColor: '#22c55e', borderDash: [4,4], pointRadius: 0, tension: 0.3, fill: false, borderWidth: 2 }}
      ]}},
      options: {{ responsive: true, plugins: {{ legend: {{ labels: {{ color: '#9ca3af', boxWidth: 12 }} }} }},
        scales: {{ x: {{ ticks: {{ color: '#6b7280', maxTicksLimit: 8 }}, grid: {{ display: false }} }},
                   y: {{ ticks: {{ color: '#6b7280', callback: v => '$' + (v >= 1000 ? (v/1000).toFixed(0) + 'K' : v) }}, grid: {{ color: '#1f2937' }}, beginAtZero: true }} }} }}
    }});"""

def sessions_cvr_chart_js(canvas_id, labels, sessions, cvr):
    return f"""new Chart(document.getElementById('{canvas_id}'), {{
      type: 'line',
      data: {{ labels: {json.dumps(labels)}, datasets: [
        {{ label: 'Sessions', data: {json.dumps(sessions)}, borderColor: '#ef4444', backgroundColor: 'transparent', yAxisID: 'y', pointRadius: 0, tension: 0.3, borderWidth: 2 }},
        {{ label: 'CVR %', data: {json.dumps(cvr)}, borderColor: '#22c55e', borderDash: [4,4], backgroundColor: 'transparent', yAxisID: 'y1', pointRadius: 0, tension: 0.3, borderWidth: 2 }}
      ]}},
      options: {{ responsive: true, interaction: {{ mode: 'index', intersect: false }},
        plugins: {{ legend: {{ labels: {{ color: '#9ca3af', boxWidth: 12 }} }} }},
        scales: {{
          x: {{ ticks: {{ color: '#6b7280', maxTicksLimit: 8 }}, grid: {{ display: false }} }},
          y: {{ position: 'left', ticks: {{ color: '#ef4444' }}, grid: {{ color: '#1f2937' }}, beginAtZero: true }},
          y1: {{ position: 'right', ticks: {{ color: '#22c55e', callback: v => v.toFixed(0) + '%' }}, grid: {{ display: false }}, beginAtZero: true }}
        }} }} }}
    );"""

cache_notice = ""
if cache_warnings:
    cache_notice = f'<div class="cache-notice">⚠ Some metrics using cached data: {", ".join(cache_warnings)}</div>'

amazon_aov_str = fmt_money(amazon_aov_val) if amazon_aov_val else "—"
shopify_aov_str = fmt_money(shopify_aov_val) if shopify_aov_val else "—"
shopify_per_unit_str = fmt_money(shopify_per_unit_val) if shopify_per_unit_val else "—"
amazon_cvr_30_str = fmt_pct(amzs_cvr_30) if amzs_cvr_30 else "—"
shopify_aov_30_str = fmt_money(shop_aov_30) if shop_aov_30 else "—"
shopify_pu_30_str = fmt_money(shop_pu_30) if shop_pu_30 else "—"

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>The Good Patch — Performance Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  body {{ background: #0a0f1c; color: #e5e7eb; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 40px; }}
  .header {{ text-align: center; margin-bottom: 30px; }}
  .logo-wrap {{ display: inline-block; background: white; padding: 18px 28px; border-radius: 12px; margin-bottom: 14px; }}
  .logo-wrap img {{ height: 120px; width: auto; display: block; }}
  .header .date {{ color: #9ca3af; font-size: 14px; margin-top: 8px; }}
  .cache-notice {{ background: rgba(234, 179, 8, 0.1); border: 1px solid rgba(234, 179, 8, 0.3); color: #facc15; padding: 10px 14px; border-radius: 8px; font-size: 12px; margin-bottom: 20px; }}
  .tabs {{ display: flex; gap: 8px; margin: 30px 0 20px; border-bottom: 1px solid #1f2937; padding-bottom: 8px; }}
  .tab {{ padding: 8px 16px; background: transparent; border: none; color: #9ca3af; cursor: pointer; border-radius: 6px; font-size: 14px; font-weight: 500; }}
  .tab.active {{ background: linear-gradient(135deg, {BRAND_COLOR}, {BRAND_COLOR_DARK}); color: white; }}
  .section {{ margin-bottom: 30px; }}
  .section-title {{ display: flex; align-items: center; gap: 10px; margin: 0 0 14px; }}
  .section-title h2 {{ font-size: 12px; font-weight: 600; margin: 0; padding-left: 8px; border-left: 3px solid {BRAND_COLOR}; text-transform: uppercase; letter-spacing: 0.6px; color: #d1d5db; }}
  .channel-icon {{ width: 20px; height: 20px; filter: brightness(0) invert(1); opacity: 0.85; }}
  .badge {{ font-size: 11px; padding: 3px 8px; background: #1f2937; color: #9ca3af; border-radius: 4px; }}
  .cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }}
  .cards-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  .cards-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
  .card {{ background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 16px; }}
  .label {{ font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
  .value {{ font-size: 24px; font-weight: 600; color: #fff; line-height: 1.2; }}
  .sub {{ font-size: 11px; color: #9ca3af; margin-top: 6px; }}
  .panel {{ display: none; }}
  .panel.active {{ display: block; }}
  .divider {{ border: 0; border-top: 1px solid #1f2937; margin: 30px 0; }}
  .chart-card {{ background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 20px; margin-top: 16px; }}
  .chart-title {{ font-size: 13px; font-weight: 500; color: #d1d5db; margin-bottom: 12px; }}
  table.products {{ width: 100%; border-collapse: collapse; background: #111827; border: 1px solid #1f2937; border-radius: 10px; overflow: hidden; }}
  table.products th {{ text-align: left; font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; padding: 12px 16px; background: #0f172a; border-bottom: 1px solid #1f2937; font-weight: 500; }}
  table.products td {{ padding: 12px 16px; border-bottom: 1px solid #1f2937; font-size: 13px; color: #e5e7eb; vertical-align: middle; }}
  table.products tr:last-child td {{ border-bottom: 0; }}
  .prod-name {{ max-width: 280px; }}
  .prod-num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .prod-bar {{ width: 40%; }}
  .bar-wrap {{ width: 100%; background: #1f2937; height: 8px; border-radius: 4px; overflow: hidden; }}
  .bar-fill {{ background: {BRAND_COLOR}; height: 100%; border-radius: 4px; }}
  @media (max-width: 900px) {{ .cards, .cards-4, .cards-3 {{ grid-template-columns: repeat(2, 1fr); }} }}
</style>
</head>
<body>
<div class="header">
  <div class="logo-wrap"><img src="{LOGO_PATH}" alt="The Good Patch" /></div>
  <div class="date">Performance Report · {DISPLAY_DATE}</div>
</div>
{cache_notice}
<div class="tabs">
  <button class="tab active" onclick="showTab(0)">Amazon</button>
  <button class="tab" onclick="showTab(1)">Shopify, Meta, Google, Klaviyo</button>
</div>

<div class="panel active" id="panel-0">
  <div class="section">
    {section_title('amazon', 'Seller Central · Amazon.com (US)', DISPLAY_DATE)}
    <div class="cards-3">
      {card(fmt_money(amazon_seller.get('ordered_product_sales')), 'Ordered Revenue', yoy_badge(amazon_seller.get('ordered_product_sales'), amazon_seller_py.get('ordered_product_sales'), fmt_money))}
      {card(fmt_num(amazon_seller.get('units_ordered')), 'Units Ordered', yoy_badge(amazon_seller.get('units_ordered'), amazon_seller_py.get('units_ordered'), fmt_num))}
      {card(amazon_aov_str, 'AOV', yoy_badge(amazon_aov_val, amazon_aov_py_val, fmt_money))}
    </div>
  </div>
  <div class="section">
    {section_title('amazon', 'Sponsored Products · La Mend (US)', DISPLAY_DATE)}
    <div class="cards">
      {card(fmt_money(amazon_ads.get('cost')), 'Ad Spend')}
      {card(fmt_money(amazon_ads.get('attributedSales14d')), 'Ad Sales')}
      {card(fmt_roas(amazon_ads.get('roas')), 'ROAS')}
      {card(fmt_pct(amazon_ads.get('acos')), 'ACOS')}
      {card(fmt_num(amazon_ads.get('clicks')), 'Clicks')}
    </div>
  </div>
  <hr class="divider">
  <div class="section">
    {section_title('amazon', 'Seller Central — 30-Day Overview', T30_LABEL)}
    <div class="cards">
      {card(fmt_money(amzs_rev_30, big=True), 'Ordered Revenue', '<div class="sub">30-day total</div>')}
      {card(fmt_num(amzs_unit_30, big=True), 'Units Ordered', f'<div class="sub">~{fmt_num(amzs_unit_30/30)} / day avg</div>' if amzs_unit_30 else '')}
      {card(fmt_num(amzs_sess_30, big=True), 'Sessions', f'<div class="sub">~{fmt_num(amzs_sess_30/30)} / day avg</div>' if amzs_sess_30 else '')}
      {card(amazon_cvr_30_str, 'Conversion Rate', '<div class="sub">units ÷ sessions</div>')}
      {card(fmt_money(amzs_rev_30/30) if amzs_rev_30 else '—', 'Daily Avg Revenue', '<div class="sub">revenue ÷ 30</div>')}
    </div>
    <div class="chart-card">
      <div class="chart-title">Daily ordered revenue (USD)</div>
      <canvas id="amazonRevChart" height="80"></canvas>
    </div>
    <div class="chart-card">
      <div class="chart-title">Sessions & conversion rate</div>
      <canvas id="amazonSessChart" height="80"></canvas>
    </div>
  </div>
  <div class="section">
    {section_title('amazon', 'Top Products by Revenue', f'{T30_LABEL} · US Marketplace')}
    <table class="products">
      <thead><tr><th>Product</th><th class="prod-num">Revenue</th><th class="prod-num">Units</th><th>Share of Top 5</th></tr></thead>
      <tbody>{product_rows()}</tbody>
    </table>
  </div>
  <div class="section">
    {section_title('amazon', 'Sponsored Products — 30-Day Overview', T30_LABEL)}
    <div class="cards-4">
      {card(fmt_money(amza_cost_30, big=True), 'Ad Spend', '<div class="sub">30-day total</div>')}
      {card(fmt_money(amza_sales_30, big=True), 'Ad Sales', '<div class="sub">30-day total</div>')}
      {card(fmt_roas(amza_roas_30), 'ROAS', '<div class="sub">sales ÷ cost</div>')}
      {card(fmt_pct(amza_acos_30), 'ACOS', '<div class="sub">cost ÷ sales</div>')}
    </div>
  </div>
</div>

<div class="panel" id="panel-1">
  <div class="section">
    {section_title('shopify', 'Shopify', DISPLAY_DATE)}
    <div class="cards-4">
      {card(fmt_money(shopify.get('net_sales')), 'Net Sales', yoy_badge(shopify.get('net_sales'), shopify_py.get('net_sales'), fmt_money))}
      {card(fmt_num(shopify.get('sm_order_count')), 'Orders', yoy_badge(shopify.get('sm_order_count'), shopify_py.get('sm_order_count'), fmt_num))}
      {card(shopify_aov_str, 'AOV', yoy_badge(shopify_aov_val, shopify_aov_py_val, fmt_money))}
      {card(shopify_per_unit_str, '$ / Unit')}
    </div>
  </div>
  <div class="section">
    {section_title('meta', 'Meta Ads', DISPLAY_DATE)}
    <div class="cards">
      {card(fmt_money(meta.get('spend')), 'Spend')}
      {card(fmt_money(meta.get('purchase_value')), 'Purchase Value')}
      {card(fmt_roas(meta.get('roas')), 'ROAS')}
      {card(fmt_money(meta.get('cpc')), 'CPC')}
      {card(fmt_pct(meta.get('ctr')), 'CTR')}
    </div>
  </div>
  <div class="section">
    {section_title('google', 'Google Ads', DISPLAY_DATE)}
    <div class="cards">
      {card(fmt_money(google_ads.get('cost')), 'Spend')}
      {card(fmt_money(google_ads.get('conversions_value')), 'Conversion Value')}
      {card(fmt_roas(google_ads.get('roas')), 'ROAS')}
      {card(fmt_money(google_ads.get('cpc')), 'CPC')}
      {card(fmt_pct(google_ads.get('ctr')), 'CTR')}
    </div>
  </div>
  <div class="section">
    {section_title('klaviyo', 'Klaviyo', DISPLAY_DATE)}
    <div class="cards">
      {card(fmt_money(klaviyo_attr.get('shopify_placed_order_value')), 'Attributed Revenue')}
      {card(fmt_num(klaviyo_attr.get('shopify_placed_order')), 'Attributed Orders')}
      {card(fmt_num(klaviyo_email.get('klaviyo_total_recipients')), 'Recipients')}
      {card(fmt_pct(klav_open), 'Open Rate')}
      {card(fmt_pct(klav_click), 'Click Rate')}
    </div>
  </div>
  <div class="section">
    {section_title('klaviyo', 'Last 5 Email Campaigns', T30_LABEL)}
    <table class="products">
      <thead><tr>
        <th>Campaign</th>
        <th class="prod-num">Sent</th>
        <th class="prod-num">Recipients</th>
        <th class="prod-num">Open</th>
        <th class="prod-num">Click</th>
        <th class="prod-num">Revenue</th>
        <th class="prod-num">Orders</th>
      </tr></thead>
      <tbody>{campaign_rows()}</tbody>
    </table>
  </div>
  <hr class="divider">
  <div class="section">
    {section_title('shopify', 'Shopify — 30-Day Overview', T30_LABEL)}
    <div class="cards-4">
      {card(fmt_money(shop_net_30, big=True), 'Net Sales', '<div class="sub">30-day total</div>')}
      {card(fmt_num(shop_ord_30, big=True), 'Orders', f'<div class="sub">~{fmt_num(shop_ord_30/30)} / day avg</div>' if shop_ord_30 else '')}
      {card(shopify_aov_30_str, 'AOV', '<div class="sub">net ÷ orders</div>')}
      {card(shopify_pu_30_str, '$ / Unit', '<div class="sub">net ÷ units</div>')}
    </div>
    <div class="chart-card">
      <div class="chart-title">Daily net sales (USD)</div>
      <canvas id="shopifyRevChart" height="80"></canvas>
    </div>
  </div>
  <div class="section">
    {section_title('meta', 'Meta Ads — 30-Day Overview', T30_LABEL)}
    <div class="cards-4">
      {card(fmt_money(meta_spend_30, big=True), 'Spend', '<div class="sub">30-day total</div>')}
      {card(fmt_money(meta_pv_30, big=True), 'Purchase Value', '<div class="sub">30-day total</div>')}
      {card(fmt_roas(meta_roas_30), 'ROAS', '<div class="sub">PV ÷ spend</div>')}
      {card(fmt_money(meta_spend_30/30) if meta_spend_30 else '—', 'Daily Avg Spend', '<div class="sub">spend ÷ 30</div>')}
    </div>
  </div>
  <div class="section">
    {section_title('google', 'Google Ads — 30-Day Overview', T30_LABEL)}
    <div class="cards-4">
      {card(fmt_money(g_spend_30, big=True), 'Spend', '<div class="sub">30-day total</div>')}
      {card(fmt_money(g_cv_30, big=True), 'Conversion Value', '<div class="sub">30-day total</div>')}
      {card(fmt_roas(g_roas_30), 'ROAS', '<div class="sub">value ÷ cost</div>')}
      {card(fmt_money(g_spend_30/30) if g_spend_30 else '—', 'Daily Avg Spend', '<div class="sub">spend ÷ 30</div>')}
    </div>
  </div>
</div>
<script>
function showTab(i) {{
  document.querySelectorAll('.tab').forEach((t, idx) => t.classList.toggle('active', idx === i));
  document.querySelectorAll('.panel').forEach((p, idx) => p.classList.toggle('active', idx === i));
}}
window.addEventListener('load', () => {{
  {revenue_chart_js('amazonRevChart', amazon_chart_labels, amazon_chart_values, amazon_chart_avg7)}
  {sessions_cvr_chart_js('amazonSessChart', amazon_chart_labels, amazon_sess_values, amazon_cvr_values)}
  {revenue_chart_js('shopifyRevChart', shopify_chart_labels, shopify_chart_values, shopify_chart_avg7, 'Daily net sales')}
}});
</script>
</body>
</html>"""

with open("index.html", "w") as f:
    f.write(html)

print(f"Dashboard generated successfully for {DISPLAY_DATE}.")
