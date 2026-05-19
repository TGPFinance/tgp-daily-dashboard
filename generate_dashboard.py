import os
import requests
from datetime import date, timedelta

SUPERMETRICS_API_KEY = os.environ["SUPERMETRICS_API_KEY"]

TODAY        = date.today()
YESTERDAY    = TODAY - timedelta(days=1)
DATE_STR     = YESTERDAY.strftime("%Y-%m-%d")
DISPLAY_DATE = YESTERDAY.strftime("%B %d, %Y")

SM_BASE = "https://api.supermetrics.com/enterprise/v2/query/data/json"

ACCOUNTS = {
    "amazon_seller": "ATVPDKIKX0DER",
    "amazon_ads":    "1221224134439971",
    "meta":          "act_898245987330933",
    "google_ads":    "9578659454",
    "klaviyo":       "the good patch",
    "shopify":       "gid://shopify/Shop/5489557622",
}

def sm_fetch(ds_id, account_id, fields, extra_params=None, timeout=180):
    params = {
        "api_key":         SUPERMETRICS_API_KEY,
        "ds_id":           ds_id,
        "ds_accounts":     account_id,
        "date_range_type": "custom",
        "start_date":      DATE_STR,
        "end_date":        DATE_STR,
        "fields":          fields,
    }
    if extra_params:
        params.update(extra_params)
    try:
        r = requests.get(SM_BASE, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        rows = data.get("data", [])
        field_list = fields.split(",")
        if len(rows) >= 2:
            return dict(zip(field_list, rows[1]))
        return {}
    except Exception as e:
        print(f"  Warning: {ds_id} fetch failed — {e}")
        return {}

print(f"Fetching data for {DISPLAY_DATE}...")

amazon_seller = sm_fetch("ASELL", ACCOUNTS["amazon_seller"],
    "ordered_product_sales,units_ordered,sessions,unit_session_percentage,page_views",
    extra_params={"report_type": "sales_and_traffic_by_date"})

amazon_ads = sm_fetch("AA", ACCOUNTS["amazon_ads"],
    "cost,attributedSales14d,roas,acos,clicks",
    extra_params={"report_type": "SponsoredProduct"})

meta = sm_fetch("FA", ACCOUNTS["meta"],
    "spend,purchase_value,roas,clicks,impressions,cpc,ctr")

google_ads = sm_fetch("AW", ACCOUNTS["google_ads"],
    "cost,conversions_value,roas,clicks,impressions,cpc,ctr")

klaviyo = sm_fetch("KLAV", ACCOUNTS["klaviyo"],
    "klaviyo_total_recipients,klaviyo_open_rate,klaviyo_click_rate",
    extra_params={"report_type": "MetricExportDaily"})

shopify = sm_fetch("SHP", ACCOUNTS["shopify"],
    "gross_sales,sm_order_count,net_sales,avg_total_sales",
    extra_params={"report_type": "Order"})

print(f"  Amazon Seller: {amazon_seller}")
print(f"  Amazon Ads:    {amazon_ads}")
print(f"  Meta:          {meta}")
print(f"  Google Ads:    {google_ads}")
print(f"  Klaviyo:       {klaviyo}")
print(f"  Shopify:       {shopify}")

def fmt_money(v):
    if v is None or v == '' or v == 0: return "—"
    try: return f"${float(v):,.2f}"
    except: return "—"

def fmt_num(v):
    if v is None or v == '' or v == 0: return "—"
    try:
        n = float(v)
        if n >= 1000: return f"{n:,.0f}"
        return f"{n:g}"
    except: return str(v)

def fmt_pct(v):
    if v is None or v == '': return "—"
    try:
        n = float(v)
        if n == 0: return "—"
        if abs(n) < 1: n *= 100
        return f"{n:,.2f}%"
    except: return "—"

def fmt_roas(v):
    if v is None or v == '' or v == 0: return "—"
    try: return f"{float(v):,.2f}×"
    except: return "—"

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>The Good Patch — Performance Report</title>
<style>
  body {{ background: #0a0f1c; color: #e5e7eb; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 40px; }}
  .header {{ text-align: center; margin-bottom: 30px; }}
  .header h1 {{ font-size: 28px; font-weight: 600; margin: 0 0 6px; }}
  .header .date {{ color: #9ca3af; font-size: 14px; }}
  .tabs {{ display: flex; gap: 8px; margin: 30px 0 20px; border-bottom: 1px solid #1f2937; padding-bottom: 8px; }}
  .tab {{ padding: 8px 16px; background: transparent; border: none; color: #9ca3af; cursor: pointer; border-radius: 6px; font-size: 14px; }}
  .tab.active {{ background: linear-gradient(135deg, #4f46e5, #7c3aed); color: white; }}
  .section {{ margin-bottom: 30px; }}
  .section h2 {{ font-size: 14px; font-weight: 600; margin: 0 0 12px; padding-left: 8px; border-left: 3px solid #6366f1; }}
  .cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }}
  .card {{ background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 16px; }}
  .value {{ font-size: 22px; font-weight: 600; margin-bottom: 4px; color: #fff; }}
  .label {{ font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; }}
  .panel {{ display: none; }}
  .panel.active {{ display: block; }}
  @media (max-width: 900px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} }}
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
    <h2>Amazon Seller Central (US)</h2>
    <div class="cards">
      <div class="card"><div class="value">{fmt_money(amazon_seller.get('ordered_product_sales'))}</div><div class="label">Ordered Revenue</div></div>
      <div class="card"><div class="value">{fmt_num(amazon_seller.get('units_ordered'))}</div><div class="label">Units Ordered</div></div>
      <div class="card"><div class="value">{fmt_num(amazon_seller.get('sessions'))}</div><div class="label">Sessions</div></div>
      <div class="card"><div class="value">{fmt_pct(amazon_seller.get('unit_session_percentage'))}</div><div class="label">Conversion Rate</div></div>
      <div class="card"><div class="value">{fmt_num(amazon_seller.get('page_views'))}</div><div class="label">Page Views</div></div>
    </div>
  </div>
  <div class="section">
    <h2>Amazon Ads (Sponsored Products)</h2>
    <div class="cards">
      <div class="card"><div class="value">{fmt_money(amazon_ads.get('cost'))}</div><div class="label">Ad Spend</div></div>
      <div class="card"><div class="value">{fmt_money(amazon_ads.get('attributedSales14d'))}</div><div class="label">Ad Sales</div></div>
      <div class="card"><div class="value">{fmt_roas(amazon_ads.get('roas'))}</div><div class="label">ROAS</div></div>
      <div class="card"><div class="value">{fmt_pct(amazon_ads.get('acos'))}</div><div class="label">ACOS</div></div>
      <div class="card"><div class="value">{fmt_num(amazon_ads.get('clicks'))}</div><div class="label">Clicks</div></div>
    </div>
  </div>
</div>
<div class="panel" id="panel-1">
  <div class="section">
    <h2>Shopify</h2>
    <div class="cards">
      <div class="card"><div class="value">{fmt_money(shopify.get('gross_sales'))}</div><div class="label">Gross Sales</div></div>
      <div class="card"><div class="value">{fmt_num(shopify.get('sm_order_count'))}</div><div class="label">Orders</div></div>
      <div class="card"><div class="value">{fmt_money(shopify.get('net_sales'))}</div><div class="label">Net Sales</div></div>
      <div class="card"><div class="value">{fmt_money(shopify.get('avg_total_sales'))}</div><div class="label">AOV</div></div>
    </div>
  </div>
  <div class="section">
    <h2>Meta Ads</h2>
    <div class="cards">
      <div class="card"><div class="value">{fmt_money(meta.get('spend'))}</div><div class="label">Spend</div></div>
      <div class="card"><div class="value">{fmt_money(meta.get('purchase_value'))}</div><div class="label">Purchase Value</div></div>
      <div class="card"><div class="value">{fmt_roas(meta.get('roas'))}</div><div class="label">ROAS</div></div>
      <div class="card"><div class="value">{fmt_money(meta.get('cpc'))}</div><div class="label">CPC</div></div>
      <div class="card"><div class="value">{fmt_pct(meta.get('ctr'))}</div><div class="label">CTR</div></div>
    </div>
  </div>
  <div class="section">
    <h2>Google Ads</h2>
    <div class="cards">
      <div class="card"><div class="value">{fmt_money(google_ads.get('cost'))}</div><div class="label">Spend</div></div>
      <div class="card"><div class="value">{fmt_money(google_ads.get('conversions_value'))}</div><div class="label">Conversion Value</div></div>
      <div class="card"><div class="value">{fmt_roas(google_ads.get('roas'))}</div><div class="label">ROAS</div></div>
      <div class="card"><div class="value">{fmt_money(google_ads.get('cpc'))}</div><div class="label">CPC</div></div>
      <div class="card"><div class="value">{fmt_pct(google_ads.get('ctr'))}</div><div class="label">CTR</div></div>
    </div>
  </div>
  <div class="section">
    <h2>Klaviyo</h2>
    <div class="cards">
      <div class="card"><div class="value">{fmt_num(klaviyo.get('klaviyo_total_recipients'))}</div><div class="label">Recipients</div></div>
      <div class="card"><div class="value">{fmt_pct(klaviyo.get('klaviyo_open_rate'))}</div><div class="label">Open Rate</div></div>
      <div class="card"><div class="value">{fmt_pct(klaviyo.get('klaviyo_click_rate'))}</div><div class="label">Click Rate</div></div>
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
