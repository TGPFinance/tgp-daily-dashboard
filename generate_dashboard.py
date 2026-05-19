import os
import json
import requests
from datetime import date, timedelta

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

ACCOUNTS = {
    "amazon_seller": "ATVPDKIKX0DER",
    "amazon_ads":    "1221224134439971",
    "meta":          "act_898245987330933",
    "google_ads":    "9578659454",
    "klaviyo":       "the good patch",
    "shopify":       "gid://shopify/Shop/5489557622",
}

def sm_fetch(ds_id, account_id, fields, start_date=DATE_STR, end_date=DATE_STR, extra_params=None, timeout=180):
    params = {"api_key": SUPERMETRICS_API_KEY, "ds_id": ds_id, "ds_accounts": account_id,
              "date_range_type": "custom", "start_date": start_date, "end_date": end_date, "fields": fields}
    if extra_params: params.update(extra_params)
    try:
        r = requests.get(SM_BASE, params=params, timeout=timeout)
        r.raise_for_status()
        rows = r.json().get("data", [])
        fl = fields.split(",")
        return dict(zip(fl, rows[1])) if len(rows) >= 2 else {}
    except Exception as e:
        print(f"  Warning: {ds_id} fetch failed — {e}")
        return {}

def sm_fetch_rows(ds_id, account_id, fields, start_date, end_date, extra_params=None, timeout=180):
    params = {"api_key": SUPERMETRICS_API_KEY, "ds_id": ds_id, "ds_accounts": account_id,
              "date_range_type": "custom", "start_date": start_date, "end_date": end_date, "fields": fields}
    if extra_params: params.update(extra_params)
    try:
        r = requests.get(SM_BASE, params=params, timeout=timeout)
        r.raise_for_status()
        rows = r.json().get("data", [])
        fl = fields.split(",")
        return [dict(zip(fl, row)) for row in rows[1:]] if len(rows) >= 2 else []
    except Exception as e:
        print(f"  Warning: {ds_id} daily fetch failed — {e}")
        return []

print(f"Fetching data for {DISPLAY_DATE}...")

amazon_seller = sm_fetch("ASELL", ACCOUNTS["amazon_seller"],
    "ordered_product_sales,units_ordered,sessions,unit_session_percentage,page_views",
    extra_params={"report_type": "sales_and_traffic_by_date"})
amazon_ads = sm_fetch("AA", ACCOUNTS["amazon_ads"],
    "cost,attributedSales14d,roas,acos,clicks",
    extra_params={"report_type": "SponsoredProduct"})
meta = sm_fetch("FA", ACCOUNTS["meta"], "spend,purchase_value,roas,clicks,impressions,cpc,ctr")
google_ads = sm_fetch("AW", ACCOUNTS["google_ads"], "cost,conversions_value,roas,clicks,impressions,cpc,ctr")
klaviyo_email = sm_fetch("KLAV", ACCOUNTS["klaviyo"],
    "klaviyo_total_recipients,klaviyo_open_rate,klaviyo_click_rate",
    extra_params={"report_type": "MetricExportDaily"})
klaviyo_attr = sm_fetch("KLAV", ACCOUNTS["klaviyo"],
    "shopify_placed_order,shopify_placed_order_value",
    extra_params={"report_type": "MetricExportAttributedCampaignDaily"})
shopify = sm_fetch("SHP", ACCOUNTS["shopify"],
    "gross_sales,sm_order_count,net_sales,avg_total_sales",
    extra_params={"report_type": "Order"})

print(f"Fetching prior year data for {PY_DATE_STR}...")
amazon_seller_py = sm_fetch("ASELL", ACCOUNTS["amazon_seller"], "ordered_product_sales,units_ordered",
    start_date=PY_DATE_STR, end_date=PY_DATE_STR, extra_params={"report_type": "sales_and_traffic_by_date"})
shopify_py = sm_fetch("SHP", ACCOUNTS["shopify"], "gross_sales,sm_order_count",
    start_date=PY_DATE_STR, end_date=PY_DATE_STR, extra_params={"report_type": "Order"})

print(f"Fetching 30-day totals & daily series ({T30_START} → {T30_END})...")
amazon_seller_30d = sm_fetch("ASELL", ACCOUNTS["amazon_seller"],
    "ordered_product_sales,units_ordered,sessions,unit_session_percentage",
    start_date=T30_START, end_date=T30_END, extra_params={"report_type": "sales_and_traffic_by_date"})
amazon_ads_30d = sm_fetch("AA", ACCOUNTS["amazon_ads"], "cost,attributedSales14d,roas,acos",
    start_date=T30_START, end_date=T30_END, extra_params={"report_type": "SponsoredProduct"})
shopify_30d = sm_fetch("SHP", ACCOUNTS["shopify"], "gross_sales,sm_order_count,net_sales,avg_total_sales",
    start_date=T30_START, end_date=T30_END, extra_params={"report_type": "Order"})
meta_30d = sm_fetch("FA", ACCOUNTS["meta"], "spend,purchase_value,roas",
    start_date=T30_START, end_date=T30_END)
google_ads_30d = sm_fetch("AW", ACCOUNTS["google_ads"], "cost,conversions_value,roas",
    start_date=T30_START, end_date=T30_END)

# Daily series for charts
amazon_daily = sm_fetch_rows("ASELL", ACCOUNTS["amazon_seller"], "date,ordered_product_sales",
    start_date=T30_START, end_date=T30_END, extra_params={"report_type": "sales_and_traffic_by_date"})
shopify_daily = sm_fetch_rows("SHP", ACCOUNTS["shopify"], "date,gross_sales",
    start_date=T30_START, end_date=T30_END, extra_params={"report_type": "Order"})

print(f"  Amazon Seller: {amazon_seller}")
print(f"  Amazon Ads:    {amazon_ads}")
print(f"  Klaviyo email: {klaviyo_email}")
print(f"  Klaviyo attr:  {klaviyo_attr}")
print(f"  Shopify:       {shopify}")
print(f"  Amazon daily:  {len(amazon_daily)} rows")
print(f"  Shopify daily: {len(shopify_daily)} rows")

# Formatters
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

def daily_avg(v, fmt=fmt_money):
    if v in (None, '', 0): return ""
    try: return f'<div class="sub">~{fmt(float(v)/30)} / day avg</div>'
    except: return ""

def card(value, label, sub=""):
    return f'<div class="card"><div class="label">{label}</div><div class="value">{value}</div>{sub}</div>'

def rolling_avg(values, window=7):
    result = []
    for i in range(len(values)):
        s = max(0, i - window + 1)
        sl = [v for v in values[s:i+1] if v is not None]
        result.append(round(sum(sl) / len(sl), 2) if sl else 0)
    return result

# Prepare chart data
def chart_data(daily_rows, value_key):
    labels = [r.get('date', '') for r in daily_rows]
    values = []
    for r in daily_rows:
        try: values.append(float(r.get(value_key, 0)))
        except: values.append(0)
    return labels, values, rolling_avg(values, 7)

amazon_labels, amazon_values, amazon_avg = chart_data(amazon_daily, 'ordered_product_sales')
shopify_labels, shopify_values, shopify_avg = chart_data(shopify_daily, 'gross_sales')

def chart_block(canvas_id, title, labels, values, avg):
    if not labels:
        return ""
    return f"""
    <div class="chart-card">
      <div class="chart-title">{title}</div>
      <canvas id="{canvas_id}" height="80"></canvas>
      <script>
        new Chart(document.getElementById('{canvas_id}'), {{
          type: 'bar',
          data: {{
            labels: {json.dumps(labels)},
            datasets: [
              {{ label: 'Daily revenue', data: {json.dumps(values)}, backgroundColor: 'rgba(99,102,241,0.7)', borderRadius: 2 }},
              {{ label: '7-day avg', type: 'line', data: {json.dumps(avg)}, borderColor: '#22c55e', borderDash: [4,4], pointRadius: 0, tension: 0.3, fill: false, borderWidth: 2 }}
            ]
          }},
          options: {{
            responsive: true,
            plugins: {{ legend: {{ labels: {{ color: '#9ca3af', boxWidth: 12 }} }} }},
            scales: {{
              x: {{ ticks: {{ color: '#6b7280', maxTicksLimit: 8 }}, grid: {{ display: false }} }},
              y: {{ ticks: {{ color: '#6b7280', callback: v => '$' + (v >= 1000 ? (v/1000).toFixed(0) + 'K' : v) }}, grid: {{ color: '#1f2937' }}, beginAtZero: true }}
            }}
          }}
        }});
      </script>
    </div>"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>The Good Patch — Performance Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  body {{ background: #0a0f1c; color: #e5e7eb; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 40px; }}
  .header {{ text-align: center; margin-bottom: 30px; }}
  .header h1 {{ font-size: 28px; font-weight: 600; margin: 0 0 6px; }}
  .header .date {{ color: #9ca3af; font-size: 14px; }}
  .tabs {{ display: flex; gap: 8px; margin: 30px 0 20px; border-bottom: 1px solid #1f2937; padding-bottom: 8px; }}
  .tab {{ padding: 8px 16px; background: transparent; border: none; color: #9ca3af; cursor: pointer; border-radius: 6px; font-size: 14px; }}
  .tab.active {{ background: linear-gradient(135deg, #4f46e5, #7c3aed); color: white; }}
  .section {{ margin-bottom: 30px; }}
  .section-title {{ display: flex; align-items: center; gap: 10px; margin: 0 0 14px; }}
  .section-title h2 {{ font-size: 12px; font-weight: 600; margin: 0; padding-left: 8px; border-left: 3px solid #6366f1; text-transform: uppercase; letter-spacing: 0.6px; color: #d1d5db; }}
  .badge {{ font-size: 11px; padding: 3px 8px; background: #1f2937; color: #9ca3af; border-radius: 4px; }}
  .cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }}
  .cards-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  .card {{ background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 16px; }}
  .label {{ font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
  .value {{ font-size: 24px; font-weight: 600; color: #fff; line-height: 1.2; }}
  .sub {{ font-size: 11px; color: #9ca3af; margin-top: 6px; }}
  .panel {{ display: none; }}
  .panel.active {{ display: block; }}
  .divider {{ border: 0; border-top: 1px solid #1f2937; margin: 30px 0; }}
  .chart-card {{ background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 20px; margin-top: 16px; }}
  .chart-title {{ font-size: 13px; font-weight: 500; color: #d1d5db; margin-bottom: 12px; }}
  @media (max-width: 900px) {{ .cards, .cards-4 {{ grid-template-columns: repeat(2, 1fr); }} }}
</style>
</head>
<body>
<div class="header">
  <h1>The Good Patch — Performance Report</h1>
  <div class="date">{DISPLAY_DATE}</div>
</div>
<div class="tabs">
  <button class="tab active" onclick="showTab(0)">Amazon</button>
  <button class="tab" onclick="showTab(1)">Shopify, Meta, Google, Klaviyo</button>
</div>

<div class="panel active" id="panel-0">
  <div class="section">
    <div class="section-title"><h2>Seller Central · Amazon.com (US)</h2><span class="badge">{DISPLAY_DATE}</span></div>
    <div class="cards">
      {card(fmt_money(amazon_seller.get('ordered_product_sales')), 'Ordered Revenue', yoy_badge(amazon_seller.get('ordered_product_sales'), amazon_seller_py.get('ordered_product_sales'), fmt_money))}
      {card(fmt_num(amazon_seller.get('units_ordered')), 'Units Ordered', yoy_badge(amazon_seller.get('units_ordered'), amazon_seller_py.get('units_ordered'), fmt_num))}
      {card(fmt_num(amazon_seller.get('sessions')), 'Sessions')}
      {card(fmt_pct(amazon_seller.get('unit_session_percentage')), 'Conversion Rate')}
      {card(fmt_num(amazon_seller.get('page_views')), 'Page Views')}
    </div>
  </div>
  <div class="section">
    <div class="section-title"><h2>Sponsored Products · La Mend (US)</h2><span class="badge">{DISPLAY_DATE}</span></div>
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
    <div class="section-title"><h2>Seller Central — 30-Day Overview</h2><span class="badge">{T30_LABEL}</span></div>
    <div class="cards">
      {card(fmt_money(amazon_seller_30d.get('ordered_product_sales'), big=True), 'Ordered Revenue', '<div class="sub">30-day total</div>')}
      {card(fmt_num(amazon_seller_30d.get('units_ordered'), big=True), 'Units Ordered', daily_avg(amazon_seller_30d.get('units_ordered'), fmt_num))}
      {card(fmt_num(amazon_seller_30d.get('sessions'), big=True), 'Sessions', daily_avg(amazon_seller_30d.get('sessions'), fmt_num))}
      {card(fmt_pct(amazon_seller_30d.get('unit_session_percentage')), 'Conversion Rate', '<div class="sub">30-day avg</div>')}
      {card(fmt_money(float(amazon_seller_30d.get('ordered_product_sales',0))/30) if amazon_seller_30d.get('ordered_product_sales') else '—', 'Daily Avg Revenue', '<div class="sub">revenue ÷ 30</div>')}
    </div>
    {chart_block('amazonChart', 'Daily ordered revenue (USD)', amazon_labels, amazon_values, amazon_avg)}
  </div>
  <div class="section">
    <div class="section-title"><h2>Sponsored Products — 30-Day Overview</h2><span class="badge">{T30_LABEL}</span></div>
    <div class="cards-4">
      {card(fmt_money(amazon_ads_30d.get('cost'), big=True), 'Ad Spend', '<div class="sub">30-day total</div>')}
      {card(fmt_money(amazon_ads_30d.get('attributedSales14d'), big=True), 'Ad Sales', '<div class="sub">30-day total</div>')}
      {card(fmt_roas(amazon_ads_30d.get('roas')), 'ROAS', '<div class="sub">30-day avg</div>')}
      {card(fmt_pct(amazon_ads_30d.get('acos')), 'ACOS', '<div class="sub">30-day avg</div>')}
    </div>
  </div>
</div>

<div class="panel" id="panel-1">
  <div class="section">
    <div class="section-title"><h2>Shopify</h2><span class="badge">{DISPLAY_DATE}</span></div>
    <div class="cards-4">
      {card(fmt_money(shopify.get('gross_sales')), 'Gross Sales', yoy_badge(shopify.get('gross_sales'), shopify_py.get('gross_sales'), fmt_money))}
      {card(fmt_num(shopify.get('sm_order_count')), 'Orders', yoy_badge(shopify.get('sm_order_count'), shopify_py.get('sm_order_count'), fmt_num))}
      {card(fmt_money(shopify.get('net_sales')), 'Net Sales')}
      {card(fmt_money(shopify.get('avg_total_sales')), 'AOV')}
    </div>
  </div>
  <div class="section">
    <div class="section-title"><h2>Meta Ads</h2><span class="badge">{DISPLAY_DATE}</span></div>
    <div class="cards">
      {card(fmt_money(meta.get('spend')), 'Spend')}
      {card(fmt_money(meta.get('purchase_value')), 'Purchase Value')}
      {card(fmt_roas(meta.get('roas')), 'ROAS')}
      {card(fmt_money(meta.get('cpc')), 'CPC')}
      {card(fmt_pct(meta.get('ctr')), 'CTR')}
    </div>
  </div>
  <div class="section">
    <div class="section-title"><h2>Google Ads</h2><span class="badge">{DISPLAY_DATE}</span></div>
    <div class="cards">
      {card(fmt_money(google_ads.get('cost')), 'Spend')}
      {card(fmt_money(google_ads.get('conversions_value')), 'Conversion Value')}
      {card(fmt_roas(google_ads.get('roas')), 'ROAS')}
      {card(fmt_money(google_ads.get('cpc')), 'CPC')}
      {card(fmt_pct(google_ads.get('ctr')), 'CTR')}
    </div>
  </div>
  <div class="section">
    <div class="section-title"><h2>Klaviyo</h2><span class="badge">{DISPLAY_DATE}</span></div>
    <div class="cards">
      {card(fmt_money(klaviyo_attr.get('shopify_placed_order_value')), 'Attributed Revenue')}
      {card(fmt_num(klaviyo_attr.get('shopify_placed_order')), 'Attributed Orders')}
      {card(fmt_num(klaviyo_email.get('klaviyo_total_recipients')), 'Recipients')}
      {card(fmt_pct(klaviyo_email.get('klaviyo_open_rate')), 'Open Rate')}
      {card(fmt_pct(klaviyo_email.get('klaviyo_click_rate')), 'Click Rate')}
    </div>
  </div>
  <hr class="divider">
  <div class="section">
    <div class="section-title"><h2>Shopify — 30-Day Overview</h2><span class="badge">{T30_LABEL}</span></div>
    <div class="cards-4">
      {card(fmt_money(shopify_30d.get('gross_sales'), big=True), 'Gross Sales', '<div class="sub">30-day total</div>')}
      {card(fmt_num(shopify_30d.get('sm_order_count'), big=True), 'Orders', daily_avg(shopify_30d.get('sm_order_count'), fmt_num))}
      {card(fmt_money(shopify_30d.get('net_sales'), big=True), 'Net Sales', '<div class="sub">30-day total</div>')}
      {card(fmt_money(shopify_30d.get('avg_total_sales')), 'AOV', '<div class="sub">30-day avg</div>')}
    </div>
    {chart_block('shopifyChart', 'Daily gross sales (USD)', shopify_labels, shopify_values, shopify_avg)}
  </div>
  <div class="section">
    <div class="section-title"><h2>Meta Ads — 30-Day Overview</h2><span class="badge">{T30_LABEL}</span></div>
    <div class="cards-4">
      {card(fmt_money(meta_30d.get('spend'), big=True), 'Spend', '<div class="sub">30-day total</div>')}
      {card(fmt_money(meta_30d.get('purchase_value'), big=True), 'Purchase Value', '<div class="sub">30-day total</div>')}
      {card(fmt_roas(meta_30d.get('roas')), 'ROAS', '<div class="sub">30-day avg</div>')}
      {card(fmt_money(float(meta_30d.get('spend',0))/30) if meta_30d.get('spend') else '—', 'Daily Avg Spend', '<div class="sub">spend ÷ 30</div>')}
    </div>
  </div>
  <div class="section">
    <div class="section-title"><h2>Google Ads — 30-Day Overview</h2><span class="badge">{T30_LABEL}</span></div>
    <div class="cards-4">
      {card(fmt_money(google_ads_30d.get('cost'), big=True), 'Spend', '<div class="sub">30-day total</div>')}
      {card(fmt_money(google_ads_30d.get('conversions_value'), big=True), 'Conversion Value', '<div class="sub">30-day total</div>')}
      {card(fmt_roas(google_ads_30d.get('roas')), 'ROAS', '<div class="sub">30-day avg</div>')}
      {card(fmt_money(float(google_ads_30d.get('cost',0))/30) if google_ads_30d.get('cost') else '—', 'Daily Avg Spend', '<div class="sub">spend ÷ 30</div>')}
    </div>
  </div>
</div>
<script>
function showTab(i) {{
  document.querySelectorAll('.tab').forEach((t, idx) => t.classList.toggle('active', idx === i));
  document.querySelectorAll('.panel').forEach((p, idx) => p.classList.toggle('active', idx === i));
}}
</script>
</body>
</html>"""

with open("index.html", "w") as f:
    f.write(html)

print(f"Dashboard generated successfully for {DISPLAY_DATE}.")
