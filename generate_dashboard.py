import os
import requests
from datetime import date, timedelta

SUPERMETRICS_API_KEY = os.environ["SUPERMETRICS_API_KEY"]

TODAY        = date.today()
YESTERDAY    = TODAY - timedelta(days=1)
DATE_STR     = YESTERDAY.strftime("%Y-%m-%d")
DISPLAY_DATE = YESTERDAY.strftime("%B %d, %Y")

# Trailing 30-day window (ending yesterday)
T30_START = (YESTERDAY - timedelta(days=29)).strftime("%Y-%m-%d")
T30_END   = DATE_STR

SM_BASE = "https://api.supermetrics.com/enterprise/v2/query/data/json"

ACCOUNTS = {
    "amazon_seller": "ATVPDKIKX0DER",
    "amazon_ads":    "1221224134439971",
    "meta":          "act_898245987330933",
    "google_ads":    "9578659454",
    "klaviyo":       "the good patch",
    "shopify":       "gid://shopify/Shop/5489557622",
}

def sm_fetch(ds_id, account_id, fields, start_date=DATE_STR, end_date=DATE_STR, extra_params=None, with_yoy=False, timeout=180):
    params = {
        "api_key":         SUPERMETRICS_API_KEY,
        "ds_id":           ds_id,
        "ds_accounts":     account_id,
        "date_range_type": "custom",
        "start_date":      start_date,
        "end_date":        end_date,
        "fields":          fields,
    }
    if extra_params:
        params.update(extra_params)
    if with_yoy:
        params["compare_type"] = "prev_year_weekday"
        params["compare_show"] = "value"
    try:
        r = requests.get(SM_BASE, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        rows = data.get("data", [])
        field_list = fields.split(",")
        if len(rows) >= 2:
            values = rows[1]
            n = len(field_list)
            current = dict(zip(field_list, values[:n]))
            prior = dict(zip(field_list, values[n:n*2])) if with_yoy and len(values) >= n*2 else {}
            return current, prior
        return {}, {}
    except Exception as e:
        print(f"  Warning: {ds_id} fetch failed — {e}")
        return {}, {}

print(f"Fetching data for {DISPLAY_DATE}...")

# --- Daily metrics (with YoY) ---
amazon_seller, amazon_seller_yoy = sm_fetch(
    "ASELL", ACCOUNTS["amazon_seller"],
    "ordered_product_sales,units_ordered,sessions,unit_session_percentage,page_views",
    extra_params={"report_type": "sales_and_traffic_by_date"},
    with_yoy=True)

amazon_ads, amazon_ads_yoy = sm_fetch(
    "AA", ACCOUNTS["amazon_ads"],
    "cost,attributedSales14d,roas,acos,clicks",
    extra_params={"report_type": "SponsoredProduct"},
    with_yoy=True)

meta, meta_yoy = sm_fetch(
    "FA", ACCOUNTS["meta"],
    "spend,purchase_value,roas,clicks,impressions,cpc,ctr",
    with_yoy=True)

google_ads, google_ads_yoy = sm_fetch(
    "AW", ACCOUNTS["google_ads"],
    "cost,conversions_value,roas,clicks,impressions,cpc,ctr",
    with_yoy=True)

klaviyo, _ = sm_fetch(
    "KLAV", ACCOUNTS["klaviyo"],
    "klaviyo_total_recipients,klaviyo_open_rate,klaviyo_click_rate",
    extra_params={"report_type": "MetricExportDaily"})

shopify, shopify_yoy = sm_fetch(
    "SHP", ACCOUNTS["shopify"],
    "gross_sales,sm_order_count,net_sales,avg_total_sales",
    extra_params={"report_type": "Order"},
    with_yoy=True)

# --- Trailing 30-day totals ---
print(f"Fetching trailing 30-day data ({T30_START} → {T30_END})...")

amazon_seller_30d, _ = sm_fetch(
    "ASELL", ACCOUNTS["amazon_seller"],
    "ordered_product_sales,units_ordered,sessions",
    start_date=T30_START, end_date=T30_END,
    extra_params={"report_type": "sales_and_traffic_by_date"})

amazon_ads_30d, _ = sm_fetch(
    "AA", ACCOUNTS["amazon_ads"],
    "cost,attributedSales14d,roas,acos",
    start_date=T30_START, end_date=T30_END,
    extra_params={"report_type": "SponsoredProduct"})

shopify_30d, _ = sm_fetch(
    "SHP", ACCOUNTS["shopify"],
    "gross_sales,sm_order_count,net_sales,avg_total_sales",
    start_date=T30_START, end_date=T30_END,
    extra_params={"report_type": "Order"})

meta_30d, _ = sm_fetch(
    "FA", ACCOUNTS["meta"],
    "spend,purchase_value,roas",
    start_date=T30_START, end_date=T30_END)

google_ads_30d, _ = sm_fetch(
    "AW", ACCOUNTS["google_ads"],
    "cost,conversions_value,roas",
    start_date=T30_START, end_date=T30_END)

print(f"  Amazon Seller: {amazon_seller} | YoY: {amazon_seller_yoy}")
print(f"  Amazon Ads:    {amazon_ads} | YoY: {amazon_ads_yoy}")
print(f"  Meta:          {meta} | YoY: {meta_yoy}")
print(f"  Google Ads:    {google_ads} | YoY: {google_ads_yoy}")
print(f"  Klaviyo:       {klaviyo}")
print(f"  Shopify:       {shopify} | YoY: {shopify_yoy}")

# --- Formatters ---
def fmt_money(v):
    if v is None or v == '' or v == 0: return "—"
    try: return f"${float(v):,.2f}"
    except: return "—"

def fmt_num(v):
    if v is None or v == '' or v == 0: return "—"
    try:
        n = float(v)
        return f"{n:,.0f}" if n >= 1000 else f"{n:g}"
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

def yoy_pct(current, prior):
    """Compute YoY % change."""
    try:
        c, p = float(current), float(prior)
        if p == 0: return None
        return ((c - p) / p) * 100
    except: return None

def yoy_badge(current, prior, fmt=fmt_money):
    """Build a YoY comparison subtitle."""
    if current in (None, '', 0) or prior in (None, '', 0):
        return ""
    pct = yoy_pct(current, prior)
    if pct is None: return ""
    color = "#22c55e" if pct >= 0 else "#ef4444"
    sign = "+" if pct >= 0 else ""
    prior_str = fmt(prior)
    return f'<div class="yoy">vs {prior_str} (PY) <span style="color:{color}">{sign}{pct:.1f}% YoY</span></div>'

# --- Build HTML ---
def card(value, label, yoy_html=""):
    return f'<div class="card"><div class="label">{label}</div><div class="value">{value}</div>{yoy_html}</div>'

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
  .section h3 {{ font-size: 13px; font-weight: 500; color: #9ca3af; margin: 24px 0 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }}
  .cards-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  .card {{ background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 16px; }}
  .label {{ font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
  .value {{ font-size: 22px; font-weight: 600; color: #fff; }}
  .yoy {{ font-size: 11px; color: #6b7280; margin-top: 6px; }}
  .panel {{ display: none; }}
  .panel.active {{ display: block; }}
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
    <h2>Amazon Seller Central (US) — {DISPLAY_DATE}</h2>
    <div class="cards">
      {card(fmt_money(amazon_seller.get('ordered_product_sales')), 'Ordered Revenue', yoy_badge(amazon_seller.get('ordered_product_sales'), amazon_seller_yoy.get('ordered_product_sales'), fmt_money))}
      {card(fmt_num(amazon_seller.get('units_ordered')), 'Units Ordered', yoy_badge(amazon_seller.get('units_ordered'), amazon_seller_yoy.get('units_ordered'), fmt_num))}
      {card(fmt_num(amazon_seller.get('sessions')), 'Sessions', yoy_badge(amazon_seller.get('sessions'), amazon_seller_yoy.get('sessions'), fmt_num))}
      {card(fmt_pct(amazon_seller.get('unit_session_percentage')), 'Conversion Rate')}
      {card(fmt_num(amazon_seller.get('page_views')), 'Page Views', yoy_badge(amazon_seller.get('page_views'), amazon_seller_yoy.get('page_views'), fmt_num))}
    </div>

    <h3>Trailing 30 days</h3>
    <div class="cards-4">
      {card(fmt_money(amazon_seller_30d.get('ordered_product_sales')), '30d Revenue')}
      {card(fmt_num(amazon_seller_30d.get('units_ordered')), '30d Units')}
      {card(fmt_num(amazon_seller_30d.get('sessions')), '30d Sessions')}
      {card('—' if not amazon_seller_30d.get('ordered_product_sales') else f"${float(amazon_seller_30d.get('ordered_product_sales'))/30:,.0f}", 'Daily Avg Revenue')}
    </div>
  </div>

  <div class="section">
    <h2>Amazon Ads (Sponsored Products)</h2>
    <div class="cards">
      {card(fmt_money(amazon_ads.get('cost')), 'Ad Spend', yoy_badge(amazon_ads.get('cost'), amazon_ads_yoy.get('cost'), fmt_money))}
      {card(fmt_money(amazon_ads.get('attributedSales14d')), 'Ad Sales', yoy_badge(amazon_ads.get('attributedSales14d'), amazon_ads_yoy.get('attributedSales14d'), fmt_money))}
      {card(fmt_roas(amazon_ads.get('roas')), 'ROAS')}
      {card(fmt_pct(amazon_ads.get('acos')), 'ACOS')}
      {card(fmt_num(amazon_ads.get('clicks')), 'Clicks', yoy_badge(amazon_ads.get('clicks'), amazon_ads_yoy.get('clicks'), fmt_num))}
    </div>

    <h3>Trailing 30 days</h3>
    <div class="cards-4">
      {card(fmt_money(amazon_ads_30d.get('cost')), '30d Ad Spend')}
      {card(fmt_money(amazon_ads_30d.get('attributedSales14d')), '30d Ad Sales')}
      {card(fmt_roas(amazon_ads_30d.get('roas')), '30d ROAS')}
      {card(fmt_pct(amazon_ads_30d.get('acos')), '30d ACOS')}
    </div>
  </div>
</div>

<div class="panel" id="panel-1">
  <div class="section">
    <h2>Shopify — {DISPLAY_DATE}</h2>
    <div class="cards-4">
      {card(fmt_money(shopify.get('gross_sales')), 'Gross Sales', yoy_badge(shopify.get('gross_sales'), shopify_yoy.get('gross_sales'), fmt_money))}
      {card(fmt_num(shopify.get('sm_order_count')), 'Orders', yoy_badge(shopify.get('sm_order_count'), shopify_yoy.get('sm_order_count'), fmt_num))}
      {card(fmt_money(shopify.get('net_sales')), 'Net Sales', yoy_badge(shopify.get('net_sales'), shopify_yoy.get('net_sales'), fmt_money))}
      {card(fmt_money(shopify.get('avg_total_sales')), 'AOV')}
    </div>
    <h3>Trailing 30 days</h3>
    <div class="cards-4">
      {card(fmt_money(shopify_30d.get('gross_sales')), '30d Gross Sales')}
      {card(fmt_num(shopify_30d.get('sm_order_count')), '30d Orders')}
      {card(fmt_money(shopify_30d.get('net_sales')), '30d Net Sales')}
      {card(fmt_money(shopify_30d.get('avg_total_sales')), '30d AOV')}
    </div>
  </div>

  <div class="section">
    <h2>Meta Ads</h2>
    <div class="cards">
      {card(fmt_money(meta.get('spend')), 'Spend', yoy_badge(meta.get('spend'), meta_yoy.get('spend'), fmt_money))}
      {card(fmt_money(meta.get('purchase_value')), 'Purchase Value', yoy_badge(meta.get('purchase_value'), meta_yoy.get('purchase_value'), fmt_money))}
      {card(fmt_roas(meta.get('roas')), 'ROAS')}
      {card(fmt_money(meta.get('cpc')), 'CPC')}
      {card(fmt_pct(meta.get('ctr')), 'CTR')}
    </div>
    <h3>Trailing 30 days</h3>
    <div class="cards-4">
      {card(fmt_money(meta_30d.get('spend')), '30d Spend')}
      {card(fmt_money(meta_30d.get('purchase_value')), '30d Purchase Value')}
      {card(fmt_roas(meta_30d.get('roas')), '30d ROAS')}
      {card('—', '')}
    </div>
  </div>

  <div class="section">
    <h2>Google Ads</h2>
    <div class="cards">
      {card(fmt_money(google_ads.get('cost')), 'Spend', yoy_badge(google_ads.get('cost'), google_ads_yoy.get('cost'), fmt_money))}
      {card(fmt_money(google_ads.get('conversions_value')), 'Conversion Value', yoy_badge(google_ads.get('conversions_value'), google_ads_yoy.get('conversions_value'), fmt_money))}
      {card(fmt_roas(google_ads.get('roas')), 'ROAS')}
      {card(fmt_money(google_ads.get('cpc')), 'CPC')}
      {card(fmt_pct(google_ads.get('ctr')), 'CTR')}
    </div>
    <h3>Trailing 30 days</h3>
    <div class="cards-4">
      {card(fmt_money(google_ads_30d.get('cost')), '30d Spend')}
      {card(fmt_money(google_ads_30d.get('conversions_value')), '30d Conv. Value')}
      {card(fmt_roas(google_ads_30d.get('roas')), '30d ROAS')}
      {card('—', '')}
    </div>
  </div>

  <div class="section">
    <h2>Klaviyo</h2>
    <div class="cards-4">
      {card(fmt_num(klaviyo.get('klaviyo_total_recipients')), 'Recipients')}
      {card(fmt_pct(klaviyo.get('klaviyo_open_rate')), 'Open Rate')}
      {card(fmt_pct(klaviyo.get('klaviyo_click_rate')), 'Click Rate')}
      {card('—', '')}
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
