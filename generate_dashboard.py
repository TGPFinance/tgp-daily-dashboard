import anthropic
import os
import requests
from datetime import date, timedelta

ANTHROPIC_API_KEY    = os.environ["ANTHROPIC_API_KEY"]
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

def sm_fetch(ds_id, account_id, fields, extra_params=None, timeout=60):
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

amazon_seller = sm_fetch(
    "ASELL", ACCOUNTS["amazon_seller"],
    "ordered_product_sales,units_ordered,sessions,unit_session_percentage,page_views",
    extra_params={"report_type": "sales_and_traffic_by_date"},
    timeout=120
)
amazon_ads = sm_fetch(
    "AA", ACCOUNTS["amazon_ads"],
    "cost,attributedSales14d,roas,acos,clicks",
    extra_params={"report_type": "SponsoredProduct"}
)
meta = sm_fetch(
    "FA", ACCOUNTS["meta"],
    "spend,purchase_value,roas,clicks,impressions,cpc,ctr"
)
google_ads = sm_fetch(
    "AW", ACCOUNTS["google_ads"],
    "cost,conversions_value,roas,clicks,impressions,cpc,ctr"
)
klaviyo = sm_fetch(
    "KLAV", ACCOUNTS["klaviyo"],
    "klaviyo_total_recipients,klaviyo_open_rate,klaviyo_click_rate,shopify_placed_order_value,shopify_conversion_rate",
    extra_params={"report_type": "MetricExportCampaign"}
)
shopify = sm_fetch(
    "SHP", ACCOUNTS["shopify"],
    "gross_sales,sm_order_count,net_sales,avg_total_sales",
    extra_params={"report_type": "Order"}
)

print(f"  Amazon Seller: {amazon_seller}")
print(f"  Amazon Ads:    {amazon_ads}")
print(f"  Meta:          {meta}")
print(f"  Google Ads:    {google_ads}")
print(f"  Klaviyo:       {klaviyo}")
print(f"  Shopify:       {shopify}")

data_summary = f"""
DATE: {DISPLAY_DATE}

AMAZON SELLER CENTRAL (US):
- Ordered Revenue: {amazon_seller.get('ordered_product_sales', 'n/a')}
- Units Ordered: {amazon_seller.get('units_ordered', 'n/a')}
- Sessions: {amazon_seller.get('sessions', 'n/a')}
- Conversion Rate: {amazon_seller.get('unit_session_percentage', 'n/a')}
- Page Views: {amazon_seller.get('page_views', 'n/a')}

AMAZON ADS (Sponsored Products):
- Ad Spend: {amazon_ads.get('cost', 'n/a')}
- Ad Sales: {amazon_ads.get('attributedSales14d', 'n/a')}
- ROAS: {amazon_ads.get('roas', 'n/a')}
- ACOS: {amazon_ads.get('acos', 'n/a')}
- Clicks: {amazon_ads.get('clicks', 'n/a')}

META ADS:
- Spend: {meta.get('spend', 'n/a')}
- Purchase Value: {meta.get('purchase_value', 'n/a')}
- ROAS: {meta.get('roas', 'n/a')}
- CPC: {meta.get('cpc', 'n/a')}
- CTR: {meta.get('ctr', 'n/a')}

GOOGLE ADS:
- Spend: {google_ads.get('cost', 'n/a')}
- Conversion Value: {google_ads.get('conversions_value', 'n/a')}
- ROAS: {google_ads.get('roas', 'n/a')}
- CPC: {google_ads.get('cpc', 'n/a')}
- CTR: {google_ads.get('ctr', 'n/a')}

KLAVIYO:
- Recipients: {klaviyo.get('klaviyo_total_recipients', 'n/a')}
- Open Rate: {klaviyo.get('klaviyo_open_rate', 'n/a')}
- Click Rate: {klaviyo.get('klaviyo_click_rate', 'n/a')}
- Order Value: {klaviyo.get('shopify_placed_order_value', 'n/a')}
- Conversion Rate: {klaviyo.get('shopify_conversion_rate', 'n/a')}

SHOPIFY:
- Gross Sales: {shopify.get('gross_sales', 'n/a')}
- Orders: {shopify.get('sm_order_count', 'n/a')}
- Net Sales: {shopify.get('net_sales', 'n/a')}
- AOV: {shopify.get('avg_total_sales', 'n/a')}
"""

DASHBOARD_PROMPT = f"""
You are building a daily performance dashboard for The Good Patch, a multi-channel ecommerce brand.

Here is today's data across all channels:
{data_summary}

Generate a complete, self-contained HTML dashboard that:
- Has a header: "The Good Patch — Performance Report" with the date {DISPLAY_DATE}
- Has two tabs: "Amazon" and "Shopify, Meta, Google, Klaviyo"
- Amazon tab: Seller Central metrics (revenue, units, sessions, CVR, page views) and Amazon Ads (spend, sales, ROAS, ACOS, CPC) as metric cards
- Second tab: Shopify, Meta Ads, Google Ads, and Klaviyo each as their own labeled section with metric cards
- Dark theme, professional analytics dashboard style
- Clean metric cards with value large and label small
- If a value is 'n/a', show it as '—' on the dashboard
- Fully self-contained with inline CSS and JS for tab switching
- No external dependencies

Return ONLY raw HTML. No markdown, no code fences, no explanation.
"""

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
message = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=4096,
    messages=[{"role": "user", "content": DASHBOARD_PROMPT}]
)

html = message.content[0].text.strip()
if html.startswith("```"):
    lines = html.split("\n")
    html = "\n".join(lines[1:-1]).strip()

with open("index.html", "w") as f:
    f.write(html)

print(f"Dashboard generated successfully for {DISPLAY_DATE}.")
