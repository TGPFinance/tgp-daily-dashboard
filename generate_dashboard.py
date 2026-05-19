import anthropic
import os
import json
import requests
from datetime import date, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY     = os.environ["ANTHROPIC_API_KEY"]
SUPERMETRICS_API_KEY  = os.environ["SUPERMETRICS_API_KEY"]

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

# ── Supermetrics fetch helper ─────────────────────────────────────────────────
def sm_fetch(ds_id, account_id, fields, settings=None):
    params = {
        "api_key":         SUPERMETRICS_API_KEY,
        "ds_id":           ds_id,
        "ds_accounts":     account_id,
        "date_range_type": "custom",
        "start_date":      DATE_STR,
        "end_date":        DATE_STR,
        "fields":          fields,
    }
    if settings:
        params["settings"] = json.dumps(settings)
    try:
        r = requests.get(SM_BASE, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        rows = data.get("data", [])
        headers = data.get("meta", {}).get("query", {}).get("fields", fields.split(","))
        if rows:
            return dict(zip(headers, rows[0]))
        return {}
    except Exception as e:
        print(f"  Warning: {ds_id} fetch failed — {e}")
        return {}

# ── Fetch all sources ─────────────────────────────────────────────────────────
print(f"Fetching data for {DISPLAY_DATE}...")

amazon_seller = sm_fetch(
    "ASELL", ACCOUNTS["amazon_seller"],
    "ordered_revenue,units_ordered,sessions,conversion_rate,page_views"
)
amazon_ads = sm_fetch(
    "AA", ACCOUNTS["amazon_ads"],
    "cost,attributed_sales_14d,roas,acos,clicks,impressions",
    settings={"report_type": "SP"}
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
    "revenue,recipients,open_rate,click_rate,placed_order_rate"
)
shopify = sm_fetch(
    "SHP", ACCOUNTS["shopify"],
    "gross_sales,orders,sessions,conversion_rate,average_order_value"
)

print("Data fetched. Generating dashboard...")

# ── Build prompt ──────────────────────────────────────────────────────────────
data_summary = f"""
DATE: {DISPLAY_DATE}

AMAZON SELLER CENTRAL (US):
- Ordered Revenue: {amazon_seller.get('ordered_revenue', 'n/a')}
- Units Ordered: {amazon_seller.get('units_ordered', 'n/a')}
- Sessions: {amazon_seller.get('sessions', 'n/a')}
- Conversion Rate: {amazon_seller.get('conversion_rate', 'n/a')}
- Page Views: {amazon_seller.get('page_views', 'n/a')}

AMAZON ADS (Sponsored Products - US):
- Ad Spend: {amazon_ads.get('cost', 'n/a')}
- Ad Sales: {amazon_ads.get('attributed_sales_14d', 'n/a')}
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
- Revenue: {klaviyo.get('revenue', 'n/a')}
- Recipients: {klaviyo.get('recipients', 'n/a')}
- Open Rate: {klaviyo.get('open_rate', 'n/a')}
- Click Rate: {klaviyo.get('click_rate', 'n/a')}
- Placed Order Rate: {klaviyo.get('placed_order_rate', 'n/a')}

SHOPIFY:
- Gross Sales: {shopify.get('gross_sales', 'n/a')}
- Orders: {shopify.get('orders', 'n/a')}
- Sessions: {shopify.get('sessions', 'n/a')}
- Conversion Rate: {shopify.get('conversion_rate', 'n/a')}
- AOV: {shopify.get('average_order_value', 'n/a')}
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
- Fully self-contained with inline CSS and JS for tab switching
- No external dependencies

Return ONLY raw HTML. No markdown, no code fences, no explanation.
"""

# ── Call Claude ───────────────────────────────────────────────────────────────
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
