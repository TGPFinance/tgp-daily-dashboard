import os
import json
import requests
from pathlib import Path
from datetime import date, datetime, timedelta
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
DEFAULT_TZ = "America/New_York"
REFRESH_RECENT_DAYS = 3  # Always re-fetch last N days (handles settling orders + API lag). Reduced from 7 for row-quota efficiency.

def is_cached_recently(cache_key, max_age_days=1):
    """Return True if cache entry exists and was written within max_age_days.
    Used to skip refetch of slow-changing data (LTV, top states, cohort prior-paid, etc.)
    that doesn't need to refresh on every workflow run — saves Supermetrics row quota."""
    entry = cache.get(cache_key)
    if not entry: return False
    cached_date = entry.get('date')
    if not cached_date: return False
    try:
        cached_dt = datetime.strptime(cached_date, "%Y-%m-%d").date()
        return (YESTERDAY - cached_dt).days < max_age_days
    except (ValueError, TypeError):
        return False

# Feature flags — flip to True when GA4 tag is fully migrated and tracking stable
SHOW_GA4_SITE_CVR = False  # Hide Site CVR section while GA4 sessions are under-reporting post-migration

# Brand
BRAND_COLOR = "#2c4ea2"
BRAND_COLOR_DARK = "#1e3a7a"
LOGO_PATH = "TGP-Logo-White.png"

ICONS = {
    'amazon':   'https://cdn.jsdelivr.net/npm/simple-icons@v11/icons/amazon.svg',
    'shopify':  'https://cdn.jsdelivr.net/npm/simple-icons@v11/icons/shopify.svg',
    'meta':     'https://cdn.jsdelivr.net/npm/simple-icons@v11/icons/meta.svg',
    'google':   'https://cdn.jsdelivr.net/npm/simple-icons@v11/icons/googleads.svg',
    'klaviyo':  'https://cdn.jsdelivr.net/npm/feather-icons@4.29.2/dist/icons/mail.svg',
    'tgp':      'TGP-Logo-White.png',
    'activity': 'https://cdn.jsdelivr.net/npm/feather-icons@4.29.2/dist/icons/activity.svg',
    'users':    'https://cdn.jsdelivr.net/npm/feather-icons@4.29.2/dist/icons/users.svg',
    'grid':     'https://cdn.jsdelivr.net/npm/feather-icons@4.29.2/dist/icons/grid.svg',
}

ACCOUNTS = {
    "amazon_seller": "ATVPDKIKX0DER",
    "amazon_ads":    "1221224134439971",
    "meta":          "act_898245987330933",
    "google_ads":    "9578659454",
    "klaviyo":       "the good patch",
    "shopify":       "gid://shopify/Shop/5489557622",
    "ga4":           "315555733",
}

SOURCES = {
    'amazon_seller': {
        'ds_id': 'ASELL', 'account_key': 'amazon_seller',
        'fields': 'ordered_product_sales,units_ordered,sessions,unit_session_percentage,page_views',
        'extra_params': {'report_type': 'sales_and_traffic_by_date'},
        'timeout': 300, 'timezone': DEFAULT_TZ,
    },
    'amazon_ads': {
        'ds_id': 'AA', 'account_key': 'amazon_ads',
        'fields': 'cost,attributedSales14d,clicks,impressions',
        'extra_params': {'report_type': 'SponsoredProduct'},
        'timeout': 300, 'timezone': DEFAULT_TZ,
    },
    'shopify': {
        'ds_id': 'SHP', 'account_key': 'shopify',
        'fields': 'gross_sales,sm_order_count,net_sales,net_quantity',
        'extra_params': {'report_type': 'Order'},
        'timeout': 180, 'timezone': DEFAULT_TZ,
    },
    'meta': {
        'ds_id': 'FA', 'account_key': 'meta',
        'fields': 'spend,purchase_value,clicks,impressions',
        'extra_params': None,
        'timeout': 180, 'timezone': DEFAULT_TZ,
    },
    'google_ads': {
        'ds_id': 'AW', 'account_key': 'google_ads',
        'fields': 'cost,conversions_value,clicks,impressions',
        'extra_params': None,
        'timeout': 180, 'timezone': DEFAULT_TZ,
    },
    'klaviyo_email': {
        'ds_id': 'KLAV', 'account_key': 'klaviyo',
        'fields': 'klaviyo_total_recipients,klaviyo_received_email,klaviyo_opened_email_unique,klaviyo_clicked_email_unique',
        'extra_params': {'report_type': 'MetricExportDaily'},
        'timeout': 180, 'timezone': DEFAULT_TZ,
    },
    'klaviyo_attr': {
        'ds_id': 'KLAV', 'account_key': 'klaviyo',
        'fields': 'shopify_placed_order,shopify_placed_order_value',
        'extra_params': {'report_type': 'MetricExportAttributedCampaignDaily'},
        'timeout': 180, 'timezone': DEFAULT_TZ,
    },
    'ga4': {
        'ds_id': 'GAWA', 'account_key': 'ga4',
        'fields': 'sessions,addToCarts,checkouts,ecommercePurchases,purchaseRevenue',
        'extra_params': None,
        'timeout': 180, 'timezone': DEFAULT_TZ,
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

def sm_fetch_rows(ds_id, account_id, fields, start_date, end_date, extra_params=None, timeout=180, retries=1, timezone=None, max_rows=None):
    params = {"api_key": SUPERMETRICS_API_KEY, "ds_id": ds_id, "ds_accounts": account_id,
              "date_range_type": "custom", "start_date": start_date, "end_date": end_date, "fields": fields}
    if extra_params: params.update(extra_params)
    if timezone: params['timezone'] = timezone
    if max_rows: params['max_rows'] = max_rows
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

    # Always refresh the last REFRESH_RECENT_DAYS days (handles settling data + API lag)
    recent_dates = {(YESTERDAY - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(REFRESH_RECENT_DAYS)}
    missing_dates = set(all_30d_dates()) - set(daily.keys())
    to_fetch = sorted(missing_dates | recent_dates)

    if not to_fetch:
        return
    start, end = to_fetch[0], to_fetch[-1]
    fields = f"date,{cfg['fields']}"
    print(f"  Fetching {source_key}: {len(to_fetch)} days ({start}→{end})")
    rows = sm_fetch_rows(cfg['ds_id'], ACCOUNTS[cfg['account_key']],
                         fields, start, end,
                         extra_params=cfg.get('extra_params'),
                         timeout=cfg.get('timeout', 180),
                         timezone=cfg.get('timezone'))
    if rows:
        for row in rows:
            d = row.get('date')
            if d:
                daily[d] = {k: v for k, v in row.items() if k != 'date'}
        return
    if DATE_STR in to_fetch:
        print(f"  {source_key}: range fetch failed, trying yesterday only")
        rows = sm_fetch_rows(cfg['ds_id'], ACCOUNTS[cfg['account_key']],
                             fields, DATE_STR, DATE_STR,
                             extra_params=cfg.get('extra_params'),
                             timeout=cfg.get('timeout', 180),
                             timezone=cfg.get('timezone'))
        if rows:
            for row in rows:
                d = row.get('date')
                if d:
                    daily[d] = {k: v for k, v in row.items() if k != 'date'}
            return
    cache_warnings.append(f"{source_key} (cached: {len(daily)}/30 days)")

def ensure_py(source_key, py_date_str=None):
    if py_date_str is None:
        py_date_str = PY_DATE_STR
    py_key = f"py_{source_key}_{py_date_str}"
    if py_key in cache:
        return
    cfg = SOURCES[source_key]
    rows = sm_fetch_rows(cfg['ds_id'], ACCOUNTS[cfg['account_key']],
                         f"date,{cfg['fields']}", py_date_str, py_date_str,
                         extra_params=cfg.get('extra_params'),
                         timeout=cfg.get('timeout', 180),
                         timezone=cfg.get('timezone'))
    if rows:
        cache[py_key] = {k: v for k, v in rows[0].items() if k != 'date'}

def ensure_top_products():
    if is_cached_recently('top_products', max_age_days=7): return
    rows = sm_fetch_rows("ASELL", ACCOUNTS["amazon_seller"],
                         "title,ordered_product_sales,units_ordered",
                         T30_START, T30_END,
                         extra_params={"report_type": "sales_and_traffic_by_asin"},
                         timeout=300, timezone=DEFAULT_TZ)
    if rows:
        cache['top_products'] = {"data": rows, "date": DATE_STR}
    elif 'top_products' in cache:
        cache_warnings.append(f"top_products (from {cache['top_products'].get('date','?')})")

def ensure_top_shopify_variants():
    if is_cached_recently('top_shopify_variants', max_age_days=7): return
    rows = sm_fetch_rows("SHP", ACCOUNTS["shopify"],
                         "title,variant_title,net_sales,net_quantity",
                         T30_START, T30_END,
                         extra_params={"report_type": "ProductSales"},
                         timeout=300, timezone=DEFAULT_TZ)
    if rows:
        cache['top_shopify_variants'] = {"data": rows, "date": DATE_STR}
    elif 'top_shopify_variants' in cache:
        cache_warnings.append(f"top_shopify_variants (from {cache['top_shopify_variants'].get('date','?')})")

def ensure_top_states():
    if is_cached_recently('top_states', max_age_days=7): return
    rows = sm_fetch_rows("SHP", ACCOUNTS["shopify"],
                         "order_shipping_province,net_sales,sm_order_count",
                         T30_START, T30_END,
                         extra_params={"report_type": "Order"},
                         timeout=180, timezone=DEFAULT_TZ)
    if rows:
        cache['top_states'] = {"data": rows, "date": DATE_STR}
    elif 'top_states' in cache:
        cache_warnings.append(f"top_states (from {cache['top_states'].get('date','?')})")

def ensure_new_returning_split():
    rows = sm_fetch_rows("SHP", ACCOUNTS["shopify"],
                         "order_is_returning_customer,net_sales,sm_order_count",
                         DATE_STR, DATE_STR,
                         extra_params={"report_type": "Order", "filters": "net_sales > 0"},
                         timeout=180, timezone=DEFAULT_TZ)
    if rows:
        cache['new_returning_yesterday'] = {"data": rows, "date": DATE_STR}

def ensure_new_returning_30d():
    rows = sm_fetch_rows("SHP", ACCOUNTS["shopify"],
                         "order_is_returning_customer,net_sales,sm_order_count",
                         T30_START, T30_END,
                         extra_params={"report_type": "Order", "filters": "net_sales > 0"},
                         timeout=180, timezone=DEFAULT_TZ)
    if rows:
        cache['new_returning_30d'] = {"data": rows, "date": DATE_STR}

def ensure_customer_ltv():
    """Pull 90-day customer-level revenue/orders for LTV and repeat purchase rate."""
    if is_cached_recently('customer_ltv', max_age_days=3): return
    ltv_start = (YESTERDAY - timedelta(days=89)).strftime("%Y-%m-%d")
    rows = sm_fetch_rows("SHP", ACCOUNTS["shopify"],
                         "customer_id,net_sales,sm_order_count",
                         ltv_start, DATE_STR,
                         extra_params={"report_type": "Order"},
                         timeout=300, timezone=DEFAULT_TZ, max_rows=10000)
    if rows:
        cache['customer_ltv'] = {"data": rows, "date": DATE_STR}

US_STATE_NAMES = {
    'AL':'Alabama','AK':'Alaska','AZ':'Arizona','AR':'Arkansas','CA':'California','CO':'Colorado',
    'CT':'Connecticut','DE':'Delaware','FL':'Florida','GA':'Georgia','HI':'Hawaii','ID':'Idaho',
    'IL':'Illinois','IN':'Indiana','IA':'Iowa','KS':'Kansas','KY':'Kentucky','LA':'Louisiana',
    'ME':'Maine','MD':'Maryland','MA':'Massachusetts','MI':'Michigan','MN':'Minnesota','MS':'Mississippi',
    'MO':'Missouri','MT':'Montana','NE':'Nebraska','NV':'Nevada','NH':'New Hampshire','NJ':'New Jersey',
    'NM':'New Mexico','NY':'New York','NC':'North Carolina','ND':'North Dakota','OH':'Ohio','OK':'Oklahoma',
    'OR':'Oregon','PA':'Pennsylvania','RI':'Rhode Island','SC':'South Carolina','SD':'South Dakota',
    'TN':'Tennessee','TX':'Texas','UT':'Utah','VT':'Vermont','VA':'Virginia','WA':'Washington',
    'WV':'West Virginia','WI':'Wisconsin','WY':'Wyoming','DC':'District of Columbia',
    'PR':'Puerto Rico','VI':'US Virgin Islands','GU':'Guam','AS':'American Samoa','MP':'Northern Mariana Islands',
}
def expand_state(code):
    raw = (code or '').strip()
    if not raw: return 'Unknown'
    upper = raw.upper()
    # 2-letter code (Amazon) → full name from map
    if upper in US_STATE_NAMES:
        return US_STATE_NAMES[upper]
    # Already a full name (Shopify gives "CALIFORNIA"), title-case it
    return raw.title()

def ensure_amazon_promo_yesterday():
    """Amazon promotional discounts (S&S, coupons, ship promos) for last 30 days, with date dim
    so render code can both pick yesterday's value and sum the full 30-day total."""
    rows = sm_fetch_rows("ASELL", ACCOUNTS["amazon_seller"],
                         "date,item_promotion_discount,ship_promotion_discount",
                         T30_START, T30_END,
                         extra_params={"report_type": "orders"},
                         timeout=300, timezone=DEFAULT_TZ, max_rows=10000)
    if rows:
        cache['amazon_promo_yesterday'] = {"data": rows, "date": DATE_STR}
    elif 'amazon_promo_yesterday' in cache:
        cache_warnings.append(f"amazon_promo_yesterday (from {cache['amazon_promo_yesterday'].get('date','?')})")

def ensure_amazon_states():
    """Top ship-to-state breakdown for Amazon Seller orders, last 30 days."""
    if is_cached_recently('amazon_states', max_age_days=7): return
    rows = sm_fetch_rows("ASELL", ACCOUNTS["amazon_seller"],
                         "ship_state,item_price,item_quantity",
                         T30_START, T30_END,
                         extra_params={"report_type": "orders"},
                         timeout=300, timezone=DEFAULT_TZ, max_rows=10000)
    if rows:
        cache['amazon_states'] = {"data": rows, "date": DATE_STR}
    elif 'amazon_states' in cache:
        cache_warnings.append(f"amazon_states (from {cache['amazon_states'].get('date','?')})")

def ensure_yoy_yesterday():
    """Same calendar date last year — Shopify net + Amazon gross + Amazon promo — for YoY card."""
    yoy_dt = YESTERDAY - timedelta(days=365)
    yoy_date = yoy_dt.strftime("%Y-%m-%d")

    shop = sm_fetch_rows("SHP", ACCOUNTS["shopify"], "net_sales,sm_order_count",
                         yoy_date, yoy_date,
                         extra_params={"report_type": "Order"},
                         timeout=180, timezone=DEFAULT_TZ)
    amz_sales = sm_fetch_rows("ASELL", ACCOUNTS["amazon_seller"], "ordered_product_sales",
                              yoy_date, yoy_date,
                              extra_params={"report_type": "sales_and_traffic_by_date"},
                              timeout=180, timezone=DEFAULT_TZ)
    amz_promo = sm_fetch_rows("ASELL", ACCOUNTS["amazon_seller"], "item_promotion_discount,ship_promotion_discount",
                              yoy_date, yoy_date,
                              extra_params={"report_type": "orders"},
                              timeout=180, timezone=DEFAULT_TZ)

    if shop or amz_sales:
        cache['yoy_yesterday'] = {
            "yoy_date": yoy_date,
            "shopify": shop or [],
            "amazon_sales": amz_sales or [],
            "amazon_promo": amz_promo or [],
            "date": DATE_STR
        }
    elif 'yoy_yesterday' in cache:
        cache_warnings.append(f"yoy_yesterday (from {cache['yoy_yesterday'].get('date','?')})")

def ensure_repeat_behavior():
    """Pull 6 months of order + line-item data for SKU affinity and time-between-orders.
    Weekly refresh — repeat patterns change slowly, no need to refetch daily."""
    if is_cached_recently('repeat_behavior', max_age_days=7): return

    # Same 6-month window as cohort (use same calc)
    first_of_this_month = YESTERDAY.replace(day=1)
    window_start_dt = first_of_this_month
    for _ in range(5):
        window_start_dt = (window_start_dt - timedelta(days=1)).replace(day=1)
    window_start = window_start_dt.strftime("%Y-%m-%d")

    # Q1: Order-level (customer_id, date) for time between orders — already aggregated per customer-day
    orders_dated = sm_fetch_rows("SHP", ACCOUNTS["shopify"],
                                  "customer_id,order_created_at_date,sm_order_count,net_sales",
                                  window_start, DATE_STR,
                                  extra_params={"report_type": "Order"},
                                  timeout=300, timezone=DEFAULT_TZ, max_rows=10000)

    # Q2 + Q3: LineItem data, chunked into 2 × 3-month windows for SKU affinity
    # (LineItem has higher row count than Order — typically 15-25K over 6 months for TGP)
    mid_dt = window_start_dt
    for _ in range(3):
        mid_dt = (mid_dt.replace(day=28) + timedelta(days=4)).replace(day=1)
    chunk1_end = (mid_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    chunk2_start = mid_dt.strftime("%Y-%m-%d")

    line_items_1 = sm_fetch_rows("SHP", ACCOUNTS["shopify"],
                                  "customer_id,order_created_at_date,title,net_sales",
                                  window_start, chunk1_end,
                                  extra_params={"report_type": "LineItem"},
                                  timeout=300, timezone=DEFAULT_TZ, max_rows=10000)
    line_items_2 = sm_fetch_rows("SHP", ACCOUNTS["shopify"],
                                  "customer_id,order_created_at_date,title,net_sales",
                                  chunk2_start, DATE_STR,
                                  extra_params={"report_type": "LineItem"},
                                  timeout=300, timezone=DEFAULT_TZ, max_rows=10000)
    line_items = (line_items_1 or []) + (line_items_2 or [])

    if orders_dated:
        cache['repeat_behavior'] = {
            "orders_dated": orders_dated,
            "line_items": line_items,
            "window_start": window_start,
            "date": DATE_STR
        }
    elif 'repeat_behavior' in cache:
        cache_warnings.append(f"repeat_behavior (from {cache['repeat_behavior'].get('date','?')})")

def ensure_cohort_data():
    """Pull 6 months of monthly order activity + 12 months of prior paying customers for cohort retention.

    Cohort definition: a customer enters cohort month M if M is their first paid order month
    AND they had no paid orders in the 12 months prior to the display window (i.e. they're
    genuinely new paying customers, not returning ones).
    """
    # Display window: 6 calendar months back from current month start
    first_of_this_month = YESTERDAY.replace(day=1)
    cohort_start_dt = first_of_this_month
    for _ in range(5):  # back 5 more months to get 6 total
        cohort_start_dt = (cohort_start_dt - timedelta(days=1)).replace(day=1)
    cohort_start = cohort_start_dt.strftime("%Y-%m-%d")

    # Prior window: 12 months BEFORE the display window — used to identify returning customers
    # who had a paid order pre-window. Split into 2 × 6-month chunks because TGP has ~12K paying
    # customers in any 12-month window, which exceeds the 10K Supermetrics row cap.
    chunk_mid_dt = cohort_start_dt
    for _ in range(6):
        chunk_mid_dt = (chunk_mid_dt - timedelta(days=1)).replace(day=1)  # first day of month -6
    prior_window_start_dt = chunk_mid_dt
    for _ in range(6):
        prior_window_start_dt = (prior_window_start_dt - timedelta(days=1)).replace(day=1)  # first day of month -12

    chunk1_start = prior_window_start_dt.strftime("%Y-%m-%d")
    chunk1_end = (chunk_mid_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    chunk2_start = chunk_mid_dt.strftime("%Y-%m-%d")
    chunk2_end = (cohort_start_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    # Q1a + Q1b: customer_ids with paid orders in prior 12 months (chunked)
    # Skip if recently cached — this is the biggest row consumer (~20K rows), but the
    # prior 12 months is historical and changes very slowly. Refresh every 14 days.
    if is_cached_recently('cohort_data', max_age_days=14) and cache.get('cohort_data', {}).get('prior_paid'):
        prior_paid = cache['cohort_data']['prior_paid']
    else:
        # Fetch net_sales as a field so we can filter in Python (query-level filter is unreliable on this endpoint)
        prior_paid_1 = sm_fetch_rows("SHP", ACCOUNTS["shopify"],
                                     "customer_id,net_sales",
                                     chunk1_start, chunk1_end,
                                     extra_params={"report_type": "Order"},
                                     timeout=300, timezone=DEFAULT_TZ, max_rows=10000)
        prior_paid_2 = sm_fetch_rows("SHP", ACCOUNTS["shopify"],
                                     "customer_id,net_sales",
                                     chunk2_start, chunk2_end,
                                     extra_params={"report_type": "Order"},
                                     timeout=300, timezone=DEFAULT_TZ, max_rows=10000)
        prior_paid = (prior_paid_1 or []) + (prior_paid_2 or [])

    # Q2: per-customer per-month order activity in display window — refresh daily because
    # the current month is still accruing
    orders = sm_fetch_rows("SHP", ACCOUNTS["shopify"],
                           "customer_id,yearMonth,sm_order_count,net_sales",
                           cohort_start, DATE_STR,
                           extra_params={"report_type": "Order"},
                           timeout=300, timezone=DEFAULT_TZ, max_rows=10000)

    if orders:
        cache['cohort_data'] = {"prior_paid": prior_paid or [], "orders": orders, "window_start": cohort_start, "date": DATE_STR}
    elif 'cohort_data' in cache:
        cache_warnings.append(f"cohort_data (from {cache['cohort_data'].get('date','?')})")

def ensure_campaigns():
    em = sm_fetch_rows("KLAV", ACCOUNTS["klaviyo"],
        "campaign_name,campaign_subject,campaign_send_date,klaviyo_total_recipients,klaviyo_open_rate,klaviyo_click_rate",
        T30_START, T30_END,
        extra_params={"report_type": "MetricExportCampaign"}, timeout=300, timezone=DEFAULT_TZ)
    # Include the flow dimension as a field so we can filter at Python level (query-level filter unreliable)
    attr = sm_fetch_rows("KLAV", ACCOUNTS["klaviyo"],
        "campaign_name,campaign_is_part_of_flow,shopify_placed_order,shopify_placed_order_value",
        T30_START, T30_END,
        extra_params={"report_type": "MetricExportAttributedCampaign"},
        timeout=300, timezone=DEFAULT_TZ)

    # Aggregate broadcast-only totals for the Email % card (30-day)
    broadcast_orders = 0
    broadcast_value = 0.0
    if attr:
        for row in attr:
            is_flow = str(row.get('campaign_is_part_of_flow', '')).strip().lower() == 'true'
            if is_flow:
                continue
            try:
                broadcast_orders += int(float(row.get('shopify_placed_order', 0) or 0))
                broadcast_value += float(row.get('shopify_placed_order_value', 0) or 0)
            except (ValueError, TypeError):
                pass

    if em:
        cache['campaigns'] = {"email": em, "attr": attr, "date": DATE_STR,
                              "broadcast_orders_30d": broadcast_orders,
                              "broadcast_value_30d": broadcast_value}
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
    futs.append(ex.submit(ensure_top_shopify_variants))
    futs.append(ex.submit(ensure_top_states))
    futs.append(ex.submit(ensure_new_returning_split))
    futs.append(ex.submit(ensure_new_returning_30d))
    futs.append(ex.submit(ensure_customer_ltv))
    futs.append(ex.submit(ensure_cohort_data))
    futs.append(ex.submit(ensure_repeat_behavior))
    futs.append(ex.submit(ensure_amazon_promo_yesterday))
    futs.append(ex.submit(ensure_amazon_states))
    futs.append(ex.submit(ensure_yoy_yesterday))
    futs.append(ex.submit(ensure_campaigns))
    for f in futs:
        f.result()

save_cache(cache)

# ── Find latest date with data for Amazon (handles Amazon's 1-2 day reporting lag) ──
def latest_date_with_data(source, key_field, max_back=5):
    """Find most recent date in cache where key_field has data > 0."""
    for d in range(max_back):
        check_date = YESTERDAY - timedelta(days=d)
        ds = check_date.strftime("%Y-%m-%d")
        data = cache['daily'].get(source, {}).get(ds, {})
        if to_float(data.get(key_field, 0)) > 0:
            return check_date
    return YESTERDAY

# Use revenue/cost as the criterion (publishes faster than sessions)
AMAZON_SELLER_DATE = latest_date_with_data('amazon_seller', 'ordered_product_sales')
AMAZON_ADS_DATE    = latest_date_with_data('amazon_ads', 'cost')
AMAZON_SELLER_DATE_STR = AMAZON_SELLER_DATE.strftime("%Y-%m-%d")
AMAZON_SELLER_DISPLAY  = AMAZON_SELLER_DATE.strftime("%B %d, %Y")
AMAZON_ADS_DATE_STR    = AMAZON_ADS_DATE.strftime("%Y-%m-%d")
AMAZON_ADS_DISPLAY     = AMAZON_ADS_DATE.strftime("%B %d, %Y")
AMAZON_PY_DATE_STR     = (AMAZON_SELLER_DATE - timedelta(days=365)).strftime("%Y-%m-%d")
AMAZON_PY_DISPLAY      = (AMAZON_SELLER_DATE - timedelta(days=365)).strftime("%Y")

# Ensure Amazon PY data is cached for the actual Amazon date used
if f"py_amazon_seller_{AMAZON_PY_DATE_STR}" not in cache:
    print(f"  Fetching Amazon PY for {AMAZON_PY_DATE_STR}")
    ensure_py('amazon_seller', AMAZON_PY_DATE_STR)
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

# Yesterday's data for sources that publish daily
shopify       = day('shopify')
meta          = day('meta')
google_ads    = day('google_ads')
klaviyo_email = day('klaviyo_email')
klaviyo_attr  = day('klaviyo_attr')

# Amazon uses latest available date (handles lag)
amazon_seller = day('amazon_seller', AMAZON_SELLER_DATE_STR)
amazon_ads    = day('amazon_ads', AMAZON_ADS_DATE_STR)

amazon_seller_py = cache.get(f"py_amazon_seller_{AMAZON_PY_DATE_STR}", {})
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

# Revenue chart: trim trailing days with no revenue
amazon_revenue_raw = daily_series('amazon_seller', 'ordered_product_sales')
while amazon_revenue_raw and amazon_revenue_raw[-1][1] == 0:
    amazon_revenue_raw.pop()
amazon_chart_labels = [d for d, _ in amazon_revenue_raw]
amazon_chart_values = [v for _, v in amazon_revenue_raw]

# Sessions/CVR chart: separate labels — trails behind revenue when Amazon publishes sessions later
amazon_sess_raw = daily_series('amazon_seller', 'sessions')
while amazon_sess_raw and amazon_sess_raw[-1][1] == 0:
    amazon_sess_raw.pop()
amazon_sess_labels = [d for d, _ in amazon_sess_raw]
amazon_sess_values = [v for _, v in amazon_sess_raw]
amazon_cvr_values  = []
for d in amazon_sess_labels:
    row = cache['daily'].get('amazon_seller', {}).get(d, {})
    cvr = to_float(row.get('unit_session_percentage', 0))
    if 0 < cvr < 1: cvr *= 100
    amazon_cvr_values.append(cvr)

# Shopify chart: include all days with sales
shopify_chart_raw = [(d, v) for d, v in daily_series('shopify', 'net_sales') if v > 0]
shopify_chart_labels = [d for d, _ in shopify_chart_raw]
shopify_chart_values = [v for _, v in shopify_chart_raw]

amazon_products = sorted(cache.get('top_products', {}).get('data', []),
                         key=lambda r: to_float(r.get('ordered_product_sales')), reverse=True)[:5]

shopify_variants = sorted(cache.get('top_shopify_variants', {}).get('data', []),
                         key=lambda r: to_float(r.get('net_sales')), reverse=True)[:5]

# ── Performance Health: New vs Returning customer split for yesterday ──
nr_data = cache.get('new_returning_yesterday', {}).get('data', [])
new_rev = 0; new_orders = 0; returning_rev = 0; returning_orders = 0
for row in nr_data:
    flag = str(row.get('order_is_returning_customer', '')).strip().lower()
    is_returning = flag in ('true', '1', 'yes', 't')
    rev = to_float(row.get('net_sales', 0))
    orders = to_float(row.get('sm_order_count', 0))
    if is_returning:
        returning_rev += rev; returning_orders += orders
    else:
        new_rev += rev; new_orders += orders

total_ad_spend = to_float(meta.get('spend')) + to_float(google_ads.get('cost')) + to_float(amazon_ads.get('cost'))
shopify_net = to_float(shopify.get('net_sales'))

# MER: 30-day trailing blended (Shopify + Amazon revenue / all ad spend incl. Amazon Ads)
total_rev_30   = shop_net_30 + amzs_rev_30
total_spend_30 = meta_spend_30 + g_spend_30 + amza_cost_30
mer_val        = safe_div(total_rev_30, total_spend_30)

# DTC ad spend only (Meta + Google) — used for nCAC and LTV:CAC since these are
# Shopify-customer metrics. Amazon Ads acquire Amazon buyers, not Shopify customers.
dtc_spend_30 = meta_spend_30 + g_spend_30
dtc_spend_day = to_float(meta.get('spend')) + to_float(google_ads.get('cost'))

# Daily nCAC (yesterday) — DTC spend / new Shopify orders
ncac_val     = safe_div(dtc_spend_day, new_orders)

# 30-day new vs returning split (for 30-day nCAC and LTV:CAC)
nr_30 = cache.get('new_returning_30d', {}).get('data', [])
new_orders_30 = 0; new_rev_30 = 0; returning_orders_30 = 0; returning_rev_30 = 0
for row in nr_30:
    flag = str(row.get('order_is_returning_customer', '')).strip().lower()
    is_returning = flag in ('true', '1', 'yes', 't')
    rev = to_float(row.get('net_sales', 0))
    orders = to_float(row.get('sm_order_count', 0))
    if is_returning:
        returning_rev_30 += rev; returning_orders_30 += orders
    else:
        new_rev_30 += rev; new_orders_30 += orders
ncac_30 = safe_div(dtc_spend_30, new_orders_30)

klaviyo_broadcast_value_30 = cache.get('campaigns', {}).get('broadcast_value_30d', 0)
email_pct    = safe_div(klaviyo_broadcast_value_30, shop_net_30)
new_rev_pct  = safe_div(new_rev, new_rev + returning_rev)

# ── Total Sales (Yesterday) + YoY ──
# Summary card uses gross Amazon (ordered_product_sales) for consistency with Amazon tab
shopify_net_yest = to_float(shopify.get('net_sales'))
amazon_gross_yest = to_float(amazon_seller.get('ordered_product_sales'))
# Promo discount still computed for the Amazon tab cards
amazon_promo_yest = 0
for row in cache.get('amazon_promo_yesterday', {}).get('data', []):
    row_date = row.get('date', '')
    if row_date == AMAZON_SELLER_DATE_STR:
        amazon_promo_yest += to_float(row.get('item_promotion_discount'))
        amazon_promo_yest += to_float(row.get('ship_promotion_discount'))
total_sales_yest = shopify_net_yest + amazon_gross_yest

# YoY: same calendar date one year ago — compare GROSS to GROSS
yoy_raw = cache.get('yoy_yesterday', {})
yoy_date_str = yoy_raw.get('yoy_date', '')
yoy_shop_net = sum(to_float(r.get('net_sales')) for r in yoy_raw.get('shopify', []))
yoy_amz_gross = sum(to_float(r.get('ordered_product_sales')) for r in yoy_raw.get('amazon_sales', []))
yoy_amz_promo = sum(to_float(r.get('item_promotion_discount')) + to_float(r.get('ship_promotion_discount'))
                    for r in yoy_raw.get('amazon_promo', []))
yoy_total = yoy_shop_net + yoy_amz_gross
yoy_pct_change = safe_div(total_sales_yest - yoy_total, yoy_total) if yoy_total > 0 else None

# Promo YoY for the Amazon tab daily card
promo_yoy_pct = safe_div(amazon_promo_yest - yoy_amz_promo, yoy_amz_promo) if yoy_amz_promo > 0 else None

# 30-day promo total from same cache (rows have date dim, sum all that fall in T30 window)
amazon_promo_30d = 0
for row in cache.get('amazon_promo_yesterday', {}).get('data', []):
    row_date = row.get('date', '')
    if T30_START <= row_date <= T30_END:
        amazon_promo_30d += to_float(row.get('item_promotion_discount'))
        amazon_promo_30d += to_float(row.get('ship_promotion_discount'))
promo_pct_of_gross_30d = safe_div(amazon_promo_30d, amzs_rev_30) if amzs_rev_30 else None

# Customer Health: 90-day LTV, repeat purchase rate, LTV:CAC
ltv_data = cache.get('customer_ltv', {}).get('data', [])
ltv_customers = {}
for row in ltv_data:
    cid = row.get('customer_id')
    if not cid: continue
    orders = to_float(row.get('sm_order_count'))
    if orders < 1: continue  # exclude refund-only / canceled-only customer rows
    rev = to_float(row.get('net_sales'))
    if rev <= 0: continue    # exclude 100%-discount comp orders (ShopMy Lookbook) and net-refunded customers
    if cid not in ltv_customers:
        ltv_customers[cid] = {'rev': 0, 'orders': 0}
    ltv_customers[cid]['rev'] += rev
    ltv_customers[cid]['orders'] += orders
unique_customers_90 = len(ltv_customers)
total_rev_90 = sum(c['rev'] for c in ltv_customers.values())
ltv_90 = safe_div(total_rev_90, unique_customers_90)
repeat_customers = sum(1 for c in ltv_customers.values() if c['orders'] >= 2)
rpr_90 = safe_div(repeat_customers, unique_customers_90)
ltv_cac_ratio = safe_div(ltv_90, ncac_30) if (ltv_90 and ncac_30) else None

# ── Cohort Retention (6-month display window, cohort = first paid order, excluding customers paid in 12 months prior) ──
from collections import defaultdict
import calendar

cohort_raw = cache.get('cohort_data', {})
cohort_prior_paid_raw = cohort_raw.get('prior_paid', [])
cohort_orders_raw = cohort_raw.get('orders', [])
cohort_window_start = cohort_raw.get('window_start', '')  # e.g. "2025-12-01"

cohort_matrix = []
cohort_weighted_avg = []
COHORT_MONTHS_DISPLAYED = 6  # show 6 cohort rows
COHORT_M_OFFSETS = 6         # M0..M5

if cohort_orders_raw and cohort_window_start:
    window_start_ym = cohort_window_start[:7]  # "2025-12"

    # Set of customer_ids who already had PAID orders BEFORE our display window
    # (filter applied in Python — query-level filter is unreliable on this endpoint)
    prior_paid_set = set()
    for row in cohort_prior_paid_raw:
        cid = row.get('customer_id')
        try:
            ns = float(row.get('net_sales', 0) or 0)
        except (ValueError, TypeError):
            ns = 0
        if cid and ns > 0:
            prior_paid_set.add(cid)

    # Parse Q2 orders and find each customer's first PAID order month in the display window
    # Filter $0 rows (ShopMy comps) at Python level since query filter is unreliable
    first_paid_month = {}
    customer_paid_months = defaultdict(set)
    for row in cohort_orders_raw:
        cid = row.get('customer_id')
        ym_raw = row.get('yearMonth', '') or ''  # format "2025|12" or "2025-12"
        try:
            ns = float(row.get('net_sales', 0) or 0)
        except (ValueError, TypeError):
            ns = 0
        if not cid or not ym_raw or ns <= 0: continue
        ym = ym_raw.replace('|', '-')
        customer_paid_months[cid].add(ym)
        if cid not in first_paid_month or ym < first_paid_month[cid]:
            first_paid_month[cid] = ym

    # Cohort = customers whose first paid order in our window is their FIRST paid order ever
    # (i.e. they were NOT in the prior-12-months paid set)
    # This is the standard DTC cohort definition: anchored on first purchase, not account creation
    customer_cohort = {}
    for cid, fpm in first_paid_month.items():
        if cid in prior_paid_set:
            continue  # returning customer — exclude
        customer_cohort[cid] = fpm

    # Build (cohort_month, calendar_month) -> set of active customer_ids
    cohort_activity = defaultdict(lambda: defaultdict(set))
    for cid, cohort_ym in customer_cohort.items():
        for ym in customer_paid_months[cid]:
            if ym >= cohort_ym:
                cohort_activity[cohort_ym][ym].add(cid)

    # Cohort sizes (denominators)
    cohort_sizes = defaultdict(int)
    for cmonth in customer_cohort.values():
        cohort_sizes[cmonth] += 1

    # Sort cohort months chronologically, keep last N
    sorted_cohorts = sorted(cohort_sizes.keys())[-COHORT_MONTHS_DISPLAYED:]
    current_ym = YESTERDAY.strftime("%Y-%m")

    def add_months(ym_str, n):
        y, m = map(int, ym_str.split('-'))
        m += n
        y += (m - 1) // 12
        m = ((m - 1) % 12) + 1
        return f"{y:04d}-{m:02d}"

    # Build the matrix: each row = (cohort_ym, size, [m0, m1, ..., m5])
    # Cells are tuples (pct, is_partial) — partial=True means target month is current month
    # (only some days observed). M0 is always (1.0, False) by definition.
    for cmonth in sorted_cohorts:
        size = cohort_sizes[cmonth]
        row_vals = []
        for offset in range(COHORT_M_OFFSETS):
            target_ym = add_months(cmonth, offset)
            if target_ym > current_ym:
                row_vals.append(None)  # future — hide
            elif offset == 0:
                row_vals.append((1.0, False))  # M0 = 100% by definition
            else:
                active = len(cohort_activity[cmonth].get(target_ym, set()))
                pct = active / size if size > 0 else 0
                is_partial = (target_ym == current_ym)
                row_vals.append((pct, is_partial))
        cohort_matrix.append((cmonth, size, row_vals))

    # Weighted average per column — EXCLUDES partial-month cells so the average represents
    # mature observation only
    for offset in range(COHORT_M_OFFSETS):
        weighted_num = 0
        weighted_den = 0
        for cmonth, size, row_vals in cohort_matrix:
            v = row_vals[offset]
            if v is None: continue
            pct, partial = v
            if partial: continue
            weighted_num += size * pct
            weighted_den += size
        cohort_weighted_avg.append((weighted_num / weighted_den, False) if weighted_den > 0 else None)


# ── Top States ──
states_data = cache.get('top_states', {}).get('data', [])
top_states = [s for s in states_data if (s.get('order_shipping_province') or '').strip()]
top_states = sorted(top_states, key=lambda r: to_float(r.get('net_sales')), reverse=True)[:5]

# ── Amazon Top Ship-To States (orders report has line-item granularity) ──
amz_states_raw = cache.get('amazon_states', {}).get('data', [])
amz_state_agg = {}
for row in amz_states_raw:
    st = (row.get('ship_state') or '').strip()
    if not st: continue
    rev = to_float(row.get('item_price'))
    qty = to_float(row.get('item_quantity'))
    if st not in amz_state_agg:
        amz_state_agg[st] = {'rev': 0, 'units': 0}
    amz_state_agg[st]['rev'] += rev
    amz_state_agg[st]['units'] += qty
amz_top_states = sorted(amz_state_agg.items(), key=lambda kv: kv[1]['rev'], reverse=True)[:5]

# ── Combined Top States (Shopify + Amazon, last 30 days) ──
combined_states = {}
for s in states_data:
    state_raw = (s.get('order_shipping_province') or '').strip()
    if not state_raw: continue
    state = expand_state(state_raw)
    if state not in combined_states:
        combined_states[state] = {'shopify': 0, 'amazon': 0, 'shopify_orders': 0, 'amazon_units': 0}
    combined_states[state]['shopify'] += to_float(s.get('net_sales'))
    combined_states[state]['shopify_orders'] += to_float(s.get('sm_order_count'))
for state_code, vals in amz_state_agg.items():
    state = expand_state(state_code)
    if state not in combined_states:
        combined_states[state] = {'shopify': 0, 'amazon': 0, 'shopify_orders': 0, 'amazon_units': 0}
    combined_states[state]['amazon'] += vals['rev']
    combined_states[state]['amazon_units'] += vals['units']
combined_top_states = sorted(
    [(state, v['shopify'] + v['amazon'], v['shopify'], v['amazon']) for state, v in combined_states.items()],
    key=lambda x: x[1], reverse=True
)[:5]

# ── Repeat Purchase Behavior: SKU Affinity + Time Between Orders ──
rb = cache.get('repeat_behavior', {})
rb_orders_raw = rb.get('orders_dated', [])
rb_lineitems_raw = rb.get('line_items', [])

# Time Between Orders: per-customer paid order dates
customer_dates = defaultdict(set)
for row in rb_orders_raw:
    cid = row.get('customer_id')
    d = row.get('order_created_at_date', '')
    ns = to_float(row.get('net_sales'))
    if cid and d and ns > 0:
        customer_dates[cid].add(d)

gaps = []
for cid, dates in customer_dates.items():
    sorted_d = sorted(dates)
    if len(sorted_d) < 2: continue
    try:
        d1 = datetime.strptime(sorted_d[0], "%Y-%m-%d")
        d2 = datetime.strptime(sorted_d[1], "%Y-%m-%d")
        gaps.append((d2 - d1).days)
    except (ValueError, TypeError):
        continue
gaps.sort()
tbo_count = len(gaps)
tbo_median = gaps[tbo_count // 2] if tbo_count else 0
tbo_pct_30 = (sum(1 for g in gaps if g <= 30) / tbo_count) if tbo_count else 0
tbo_pct_90 = (sum(1 for g in gaps if g <= 90) / tbo_count) if tbo_count else 0
tbo_buckets = [("0–7d", 0), ("8–14d", 0), ("15–30d", 0), ("31–60d", 0), ("61–90d", 0), ("90d+", 0)]
tbo_dict = dict(tbo_buckets)
for g in gaps:
    if g <= 7: tbo_dict["0–7d"] += 1
    elif g <= 14: tbo_dict["8–14d"] += 1
    elif g <= 30: tbo_dict["15–30d"] += 1
    elif g <= 60: tbo_dict["31–60d"] += 1
    elif g <= 90: tbo_dict["61–90d"] += 1
    else: tbo_dict["90d+"] += 1
tbo_buckets = [(name, tbo_dict[name]) for name, _ in tbo_buckets]
tbo_bucket_max = max((c for _, c in tbo_buckets), default=1) or 1

# SKU Affinity: per-customer per-date set of product titles
customer_orders_products = defaultdict(lambda: defaultdict(set))
for row in rb_lineitems_raw:
    cid = row.get('customer_id')
    d = row.get('order_created_at_date', '')
    title = (row.get('title') or '').strip()
    ns = to_float(row.get('net_sales'))
    if cid and d and title and ns > 0:
        customer_orders_products[cid][d].add(title)

# Pair first product → second product. Primary product = first alphabetically (deterministic).
sku_pairs = defaultdict(lambda: defaultdict(int))
sku_repeat_totals = defaultdict(int)
sku_first_totals = defaultdict(int)
for cid, orders in customer_orders_products.items():
    if not orders: continue
    sorted_dates = sorted(orders.keys())
    first_prods = sorted(orders[sorted_dates[0]])
    if not first_prods: continue
    primary_first = first_prods[0]
    sku_first_totals[primary_first] += 1
    if len(sorted_dates) < 2: continue
    second_prods = sorted(orders[sorted_dates[1]])
    if not second_prods: continue
    primary_second = second_prods[0]
    sku_pairs[primary_first][primary_second] += 1
    sku_repeat_totals[primary_first] += 1

# Top 5 first products by N customers who returned for a 2nd order
sku_top = sorted(sku_repeat_totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
sku_rows_data = []
for product, n in sku_top:
    second_counts = sku_pairs[product]
    if second_counts:
        most_common, mc_count = max(second_counts.items(), key=lambda kv: kv[1])
        pct_bought = mc_count / n if n else 0
    else:
        most_common, pct_bought = '—', 0
    repeat_rate = n / sku_first_totals[product] if sku_first_totals[product] else 0
    sku_rows_data.append({
        'first': product, 'n': n,
        'second': most_common,
        'label': 'restock' if most_common == product else 'cross-sell',
        'pct_bought': pct_bought,
        'repeat_rate': repeat_rate,
    })

# ── Site CVR (GA4 sessions / Shopify orders) ──
ga4_yesterday = day('ga4')
ga4_sessions  = to_float(ga4_yesterday.get('sessions'))
shopify_orders_yest = to_float(shopify.get('sm_order_count'))
site_cvr_val  = safe_div(shopify_orders_yest, ga4_sessions)

# 30-day Site CVR
ga4_sessions_30 = sum_field('ga4', 'sessions')
site_cvr_30     = safe_div(shop_ord_30, ga4_sessions_30)

camp_data = cache.get('campaigns', {})
camp_email = camp_data.get('email', [])
camp_attr = {c.get('campaign_name'): c for c in camp_data.get('attr', [])}
for c in camp_email:
    a = camp_attr.get(c.get('campaign_name'), {})
    c['shopify_placed_order'] = a.get('shopify_placed_order')
    c['shopify_placed_order_value'] = a.get('shopify_placed_order_value')
klaviyo_campaigns = sorted(camp_email, key=lambda c: c.get('campaign_send_date', ''), reverse=True)[:5]

print(f"  Days cached: amazon_seller={len(cache['daily'].get('amazon_seller',{}))}, amazon_ads={len(cache['daily'].get('amazon_ads',{}))}, shopify={len(cache['daily'].get('shopify',{}))}")
print(f"  Amazon Seller showing: {AMAZON_SELLER_DATE_STR} | Amazon Ads showing: {AMAZON_ADS_DATE_STR}")
if cache_warnings:
    print(f"  Cache fallbacks (not displayed in dashboard): {cache_warnings}")

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

def shorten_product_title(title):
    """Take text before first comma, append any trailing parenthetical (e.g. '(8 Total Patches)')."""
    if not title:
        return 'Unknown'
    before_comma = title.split(',')[0].strip()
    stripped = title.rstrip()
    if stripped.endswith(')'):
        paren_start = stripped.rfind('(')
        if paren_start != -1:
            return f"{before_comma} {stripped[paren_start:]}"
    return before_comma

def yoy_badge(cur, prior, fmt=fmt_money, py_year=None):
    if cur in (None, '', 0) or prior in (None, '', 0): return ""
    if py_year is None: py_year = PY_DISPLAY
    try:
        c, p = float(cur), float(prior)
        if p == 0: return ""
        pct = ((c - p) / p) * 100
        color = "#22c55e" if pct >= 0 else "#ef4444"
        sign = "+" if pct >= 0 else ""
        return f'<div class="sub">vs {fmt(prior)} ({py_year}) <span style="color:{color};font-weight:500">{sign}{pct:.1f}% YoY</span></div>'
    except: return ""

def card(value, label, sub=""):
    return f'<div class="card"><div class="label">{label}</div><div class="value">{value}</div>{sub}</div>'

def section_title(icon_key, title, badge=''):
    if icon_key == 'tgp':
        icon = f'<img class="tgp-icon" src="{ICONS[icon_key]}" alt="" />'
    elif icon_key:
        icon = f'<img class="channel-icon" src="{ICONS[icon_key]}" alt="" />'
    else:
        icon = ''
    badge_html = f'<span class="badge">{badge}</span>' if badge else ''
    return f'<div class="section-title">{icon}<h2>{title}</h2>{badge_html}</div>'

def render_cohort_table():
    """Render cohort retention heatmap. Returns empty string if no data."""
    if not cohort_matrix:
        return ""

    benchmarks = ['100%', '25-35%', '15-22%', '10-15%', '7-12%', '5-10%']
    current_ym = YESTERDAY.strftime("%Y-%m")

    def fmt_cohort_label(ym):
        y, m = ym.split('-')
        return f"{calendar.month_abbr[int(m)]} {y}"

    def cell_html(v, is_m0=False):
        if v is None:
            return '<td class="ck null">—</td>'
        pct, partial = v if isinstance(v, tuple) else (v, False)
        if is_m0 or pct >= 1.0:
            return f'<td class="ck full">{int(round(pct*100))}%</td>'
        # Scale intensity 0-100% → alpha 0.18-0.7
        alpha = min(0.70, max(0.18, pct * 2.2))
        cls = "ck ck-partial" if partial else "ck"
        mark = '<span class="ck-pmark">*</span>' if partial else ''
        return f'<td class="{cls}" style="background:rgba(44,78,162,{alpha:.2f})">{int(round(pct*100))}%{mark}</td>'

    body_rows = ""
    for cmonth, size, row_vals in cohort_matrix:
        is_partial = (cmonth == current_ym)
        label = fmt_cohort_label(cmonth) + ("*" if is_partial else "")
        cells = "".join(cell_html(v, is_m0=(i==0)) for i, v in enumerate(row_vals))
        body_rows += f'<tr><td class="ch-label">{label}</td><td class="ch-size">{size:,}</td>{cells}</tr>'

    avg_cells = "".join(cell_html(v, is_m0=(i==0)) for i, v in enumerate(cohort_weighted_avg))
    bench_cells = "".join(f'<td class="ck bench">{b}</td>' for b in benchmarks)

    has_partial_cohort = any(c[0] == current_ym for c in cohort_matrix)
    has_partial_cell = any(isinstance(v, tuple) and v[1] for _, _, rv in cohort_matrix for v in rv)
    note_parts = []
    if has_partial_cohort: note_parts.append("*Partial cohort (month-to-date).")
    if has_partial_cell:   note_parts.append("italic = partial-month observation; weighted avg excludes these.")
    note_parts.append("Benchmarks based on Shopify/Klaviyo/Lifetimely wellness DTC reports (2024-25); range = average-to-strong.")
    footnote = " ".join(note_parts)

    return f'''
<div class="section">
  {section_title('grid', 'New Customer Cohort Retention', '6 months · first paid order, excluding 12-mo prior payers')}
  <div class="cohort-wrap">
    <table class="cohort-tbl">
      <thead>
        <tr>
          <th class="ch-label">Cohort</th>
          <th class="ch-size">Size</th>
          <th>M0</th><th>M1</th><th>M2</th><th>M3</th><th>M4</th><th>M5</th>
        </tr>
      </thead>
      <tbody>
        {body_rows}
        <tr class="ch-avg-row">
          <td class="ch-label" colspan="2">Your weighted avg</td>
          {avg_cells}
        </tr>
        <tr class="ch-bench-row">
          <td class="ch-label" colspan="2">Wellness DTC benchmark</td>
          {bench_cells}
        </tr>
      </tbody>
    </table>
    <div class="cohort-foot">{footnote}</div>
  </div>
</div>'''


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
        title = shorten_product_title(p.get('title'))
        out += f"""
        <tr>
          <td class="prod-name">{title}</td>
          <td class="prod-num">${rev:,.0f}</td>
          <td class="prod-num">{units:,.0f}</td>
          <td class="prod-bar"><div class="bar-wrap"><div class="bar-fill" style="width:{share:.1f}%"></div></div></td>
        </tr>"""
    return out

def shopify_variant_rows():
    top_total = sum(to_float(v.get('net_sales')) for v in shopify_variants) or 1
    out = ""
    for v in shopify_variants:
        sales = to_float(v.get('net_sales'))
        qty = to_float(v.get('net_quantity'))
        share = (sales / top_total) * 100
        product = v.get('title') or 'Unknown'
        variant = v.get('variant_title') or ''
        name = f"{product} — {variant}" if variant else product
        out += f"""
        <tr>
          <td class="prod-name">{name}</td>
          <td class="prod-num">${sales:,.0f}</td>
          <td class="prod-num">{qty:,.0f}</td>
          <td class="prod-bar"><div class="bar-wrap"><div class="bar-fill" style="width:{share:.1f}%"></div></div></td>
        </tr>"""
    return out

def state_rows():
    if not top_states: return '<tr><td colspan="4" style="text-align:center;color:#6b7280">No state data available</td></tr>'
    top_total = to_float(top_states[0].get('net_sales')) or 1
    out = ""
    for s in top_states:
        rev = to_float(s.get('net_sales'))
        orders = to_float(s.get('sm_order_count'))
        share = (rev / top_total) * 100
        state = expand_state(s.get('order_shipping_province') or 'Unknown')
        out += f"""
        <tr>
          <td class="prod-name">{state}</td>
          <td class="prod-num">${rev:,.0f}</td>
          <td class="prod-num">{orders:,.0f}</td>
          <td class="prod-bar"><div class="bar-wrap"><div class="bar-fill" style="width:{share:.1f}%"></div></div></td>
        </tr>"""
    return out

def amazon_state_rows():
    if not amz_top_states: return '<tr><td colspan="4" style="text-align:center;color:#6b7280">No state data available</td></tr>'
    top_total = amz_top_states[0][1]['rev'] or 1
    out = ""
    for state_code, vals in amz_top_states:
        rev = vals['rev']; units = vals['units']
        share = (rev / top_total) * 100
        state = expand_state(state_code)
        out += f"""
        <tr>
          <td class="prod-name">{state}</td>
          <td class="prod-num">${rev:,.0f}</td>
          <td class="prod-num">{units:,.0f}</td>
          <td class="prod-bar"><div class="bar-wrap"><div class="bar-fill" style="width:{share:.1f}%"></div></div></td>
        </tr>"""
    return out

def combined_state_rows():
    if not combined_top_states: return '<tr><td colspan="5" style="text-align:center;color:#6b7280">No state data available</td></tr>'
    top_total = combined_top_states[0][1] or 1
    out = ""
    for state, total, shop, amz in combined_top_states:
        share = (total / top_total) * 100
        out += f"""
        <tr>
          <td class="prod-name">{state}</td>
          <td class="prod-num">${total:,.0f}</td>
          <td class="prod-num sub-channel">${shop:,.0f}</td>
          <td class="prod-num sub-channel">${amz:,.0f}</td>
          <td class="prod-bar"><div class="bar-wrap"><div class="bar-fill" style="width:{share:.1f}%"></div></div></td>
        </tr>"""
    return out

def sku_affinity_rows():
    if not sku_rows_data: return '<tr><td colspan="5" style="text-align:center;color:#6b7280">Not enough repeat purchase data yet</td></tr>'
    max_n = sku_rows_data[0]['n'] or 1
    out = ""
    for r in sku_rows_data:
        bar_pct = (r['n'] / max_n) * 100
        pct_color = '#22c55e' if r['pct_bought'] >= 0.4 else ('#facc15' if r['pct_bought'] >= 0.2 else '#94a3b8')
        out += f"""
        <tr>
          <td class="prod-name">{r['first']}</td>
          <td class="prod-num">{r['n']:,}</td>
          <td class="prod-name">{r['second']} <span class="sku-label">· {r['label']}</span></td>
          <td class="prod-num" style="color:{pct_color}">{r['pct_bought']*100:.0f}%</td>
          <td class="prod-bar"><div class="bar-wrap"><div class="bar-fill" style="width:{bar_pct:.1f}%"></div></div> <span class="sub-channel" style="font-size:11px">{r['repeat_rate']*100:.0f}%</span></td>
        </tr>"""
    return out

def tbo_histogram_bars():
    """Render the time-between-orders histogram as flexbox bars."""
    if not tbo_buckets or tbo_bucket_max == 0:
        return '<div style="color:#6b7280;text-align:center;padding:20px">Not enough repeat purchase data yet</div>'
    out = '<div class="tbo-hist">'
    for i, (name, count) in enumerate(tbo_buckets):
        pct = (count / tbo_count * 100) if tbo_count else 0
        height_pct = (count / tbo_bucket_max * 100) if tbo_bucket_max else 0
        # Buckets at 31+ days are de-emphasized
        bar_color = BRAND_COLOR if i < 3 else ('#1e3a7a' if i < 5 else '#475569')
        out += f'''
        <div class="tbo-col">
          <div class="tbo-val">{pct:.0f}%</div>
          <div class="tbo-bar" style="height:{max(height_pct, 3):.0f}%; background:{bar_color}"></div>
          <div class="tbo-label">{name}</div>
        </div>'''
    out += '</div>'
    return out

def benchmark_status(label, color):
    return f'<div class="sub" style="color:{color}">{label}</div>'

def bm_mer(v):
    if v is None: return ''
    if v >= 4: return benchmark_status('Target 3×+ · excellent', '#22c55e')
    if v >= 3: return benchmark_status('Target 3×+ · on track', '#22c55e')
    if v >= 2: return benchmark_status('Target 3×+ · close', '#facc15')
    return benchmark_status('Target 3×+ · below', '#ef4444')

def bm_ncac(v, aov):
    if v is None or aov in (None, 0): return ''
    r = v / aov
    if r < 0.5:  return benchmark_status(f'{r*100:.0f}% of AOV · profitable on first', '#22c55e')
    if r < 1.0:  return benchmark_status(f'{r*100:.0f}% of AOV · breakeven on first', '#facc15')
    return benchmark_status(f'{r*100:.0f}% of AOV · loss on first (needs LTV)', '#ef4444')

def bm_email_pct(v):
    if v is None: return ''
    pct = v * 100 if abs(v) < 1 else v
    if pct >= 30: return benchmark_status('Target 25-30% · strong', '#22c55e')
    if pct >= 20: return benchmark_status('Target 25-30% · healthy', '#22c55e')
    if pct >= 10: return benchmark_status('Target 25-30% · below', '#facc15')
    return benchmark_status('Target 25-30% · low', '#ef4444')

def bm_new_rev(v):
    if v is None: return ''
    pct = v * 100 if abs(v) < 1 else v
    if pct >= 50: return benchmark_status('Growth-stage mix', '#22c55e')
    if pct >= 30: return benchmark_status('Balanced acquisition/retention', '#22c55e')
    return benchmark_status('Retention-dominated', '#9ca3af')

def yoy_change_badge(pct, yoy_date_str, yoy_value):
    """Render YoY change badge — green if growing, red if declining, gray if N/A."""
    if pct is None:
        return f'<div class="sub" style="color:#6b7280">vs {yoy_date_str or "prior year"}: no data</div>'
    color = '#22c55e' if pct >= 0 else '#ef4444'
    sign = '+' if pct >= 0 else ''
    return f'<div class="sub"><span style="color:{color};font-weight:500">{sign}{pct*100:.1f}%</span> <span style="color:#6b7280">vs {yoy_date_str} (${yoy_value:,.0f})</span></div>'

def bm_cvr(v):
    if v is None: return ''
    pct = v * 100 if abs(v) < 1 else v
    if pct >= 3: return benchmark_status('Target 2-3% · strong', '#22c55e')
    if pct >= 2: return benchmark_status('Target 2-3% · healthy', '#22c55e')
    if pct >= 1: return benchmark_status('Target 2-3% · below', '#facc15')
    return benchmark_status('Target 2-3% · low', '#ef4444')

def bm_ltv_cac(v):
    if v is None: return ''
    if v >= 3: return benchmark_status('Target 3×+ · healthy', '#22c55e')
    if v >= 2: return benchmark_status('Target 3×+ · close', '#facc15')
    return benchmark_status('Target 3×+ · below', '#ef4444')

def bm_rpr(v):
    if v is None: return ''
    pct = v * 100 if abs(v) < 1 else v
    if pct >= 30: return benchmark_status('Target 25-30% · strong', '#22c55e')
    if pct >= 20: return benchmark_status('Target 25-30% · healthy', '#22c55e')
    if pct >= 10: return benchmark_status('Target 25-30% · building', '#facc15')
    return benchmark_status('Target 25-30% · low', '#ef4444')

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

amazon_chart_avg7   = rolling_avg(amazon_chart_values, 7)
shopify_chart_avg7  = rolling_avg(shopify_chart_values, 7)

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
  .logo-wrap {{ display: inline-block; margin-bottom: 14px; }}
  .logo-wrap img {{ height: 100px; width: auto; display: block; }}
  .header .date {{ color: #9ca3af; font-size: 14px; margin-top: 8px; }}
  .tabs {{ display: flex; gap: 8px; margin: 30px 0 20px; border-bottom: 1px solid #1f2937; padding-bottom: 8px; }}
  .tab {{ padding: 8px 16px; background: transparent; border: none; color: #9ca3af; cursor: pointer; border-radius: 6px; font-size: 14px; font-weight: 500; }}
  .tab.active {{ background: linear-gradient(135deg, {BRAND_COLOR}, {BRAND_COLOR_DARK}); color: white; }}
  .section {{ margin-bottom: 30px; }}
  .summary-block {{ background: rgba(44, 78, 162, 0.06); border: 1px solid rgba(44, 78, 162, 0.18); border-radius: 12px; padding: 20px 20px 4px; margin-bottom: 28px; }}
  .summary-block .section {{ margin-bottom: 18px; }}
  .section-divider {{ display: flex; align-items: center; gap: 14px; margin: 8px 0 24px; }}
  .section-divider .line {{ flex: 1; height: 1px; background: linear-gradient(to right, transparent, rgba(255,255,255,0.18), transparent); }}
  .section-divider .label {{ font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: #6b7280; }}
  .section-title {{ display: flex; align-items: center; gap: 10px; margin: 0 0 14px; }}
  .section-title h2 {{ font-size: 12px; font-weight: 600; margin: 0; padding-left: 8px; border-left: 3px solid {BRAND_COLOR}; text-transform: uppercase; letter-spacing: 0.6px; color: #d1d5db; }}
  .channel-icon {{ width: 20px; height: 20px; filter: brightness(0) invert(1); opacity: 0.85; }}
  .tgp-icon {{ height: 22px; width: auto; opacity: 0.95; }}
  .cohort-wrap {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 14px; }}
  .cohort-tbl {{ width: 100%; border-collapse: separate; border-spacing: 3px; font-size: 11px; }}
  .cohort-tbl th {{ color: #9ca3af; font-weight: 500; padding: 4px 6px; text-transform: uppercase; letter-spacing: 0.6px; font-size: 9px; }}
  .cohort-tbl th.ch-label {{ text-align: left; }}
  .cohort-tbl th.ch-size {{ text-align: right; }}
  .cohort-tbl td.ch-label {{ color: #d1d5db; padding: 3px 6px; }}
  .cohort-tbl td.ch-size {{ color: #9ca3af; padding: 3px 6px; text-align: right; }}
  .cohort-tbl td.ck {{ color: white; text-align: center; padding: 6px; border-radius: 4px; font-weight: 500; }}
  .cohort-tbl td.ck.full {{ background: {BRAND_COLOR}; }}
  .cohort-tbl td.ck-partial {{ opacity: 0.65; font-style: italic; }}
  .cohort-tbl .ck-pmark {{ font-size: 8px; vertical-align: super; margin-left: 1px; opacity: 0.7; }}
  .cohort-tbl td.ck.null {{ background: rgba(255,255,255,0.03); color: #4b5563; font-weight: 400; }}
  .cohort-tbl tr.ch-avg-row td {{ font-style: italic; font-size: 10px; color: #6b7280; }}
  .cohort-tbl tr.ch-avg-row td.ck {{ font-style: normal; font-size: 10px; color: white; }}
  .cohort-tbl tr.ch-bench-row td {{ color: #facc15; font-size: 10px; font-weight: 500; }}
  .cohort-tbl td.ck.bench {{ background: rgba(255,255,255,0.04); border: 1px dashed rgba(250,204,21,0.4); color: #facc15; padding: 5px; font-size: 10px; }}
  .cohort-foot {{ margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.06); font-size: 10px; color: #6b7280; line-height: 1.5; }}
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
  table.products th.prod-num {{ text-align: right; }}
  table.products td {{ padding: 12px 16px; border-bottom: 1px solid #1f2937; font-size: 13px; color: #e5e7eb; vertical-align: middle; }}
  table.products tr:last-child td {{ border-bottom: 0; }}
  .prod-name {{ max-width: 280px; }}
  .prod-num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .prod-num.sub-channel {{ color: #94a3b8; font-size: 12px; }}
  .prod-bar {{ width: 25%; }}
  .sku-label {{ color: #64748b; font-size: 11px; }}
  .tbo-stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px; }}
  .tbo-stat {{ padding: 12px 14px; background: #0a1220; border: 0.5px solid #1f2937; border-radius: 6px; }}
  .tbo-stat .lbl {{ font-size: 10px; color: #64748b; letter-spacing: 0.05em; text-transform: uppercase; }}
  .tbo-stat .val {{ font-size: 22px; font-weight: 500; color: #e5e7eb; margin-top: 2px; }}
  .tbo-hist {{ display: flex; align-items: flex-end; gap: 10px; height: 140px; padding: 0 6px; }}
  .tbo-col {{ flex: 1; display: flex; flex-direction: column; align-items: center; gap: 6px; height: 100%; }}
  .tbo-val {{ font-size: 11px; color: #cbd5e1; font-weight: 500; }}
  .tbo-bar {{ width: 100%; border-radius: 3px 3px 0 0; flex-grow: 0; min-height: 4px; }}
  .tbo-col {{ justify-content: flex-end; }}
  .tbo-label {{ font-size: 10px; color: #64748b; text-align: center; }}
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
<div class="tabs">
  <button class="tab active" onclick="showTab(0)">Summary</button>
  <button class="tab" onclick="showTab(1)">Amazon</button>
  <button class="tab" onclick="showTab(2)">Shopify, Meta, Google, Klaviyo</button>
</div>

<div class="panel" id="panel-1">
  <div class="section">
    {section_title('amazon', 'Seller Central · Amazon.com (US)', AMAZON_SELLER_DISPLAY)}
    <div class="cards-4">
      {card(fmt_money(amazon_seller.get('ordered_product_sales')), 'Ordered Revenue', yoy_badge(amazon_seller.get('ordered_product_sales'), amazon_seller_py.get('ordered_product_sales'), fmt_money, AMAZON_PY_DISPLAY))}
      {card(fmt_money(amazon_promo_yest), 'Promo Discount', f'<div class="sub">S&amp;S + coupons + ship promos</div>' + (yoy_change_badge(promo_yoy_pct, AMAZON_PY_DISPLAY, yoy_amz_promo) if promo_yoy_pct is not None else ''))}
      {card(fmt_num(amazon_seller.get('units_ordered')), 'Units Ordered', yoy_badge(amazon_seller.get('units_ordered'), amazon_seller_py.get('units_ordered'), fmt_num, AMAZON_PY_DISPLAY))}
      {card(amazon_aov_str, 'AOV', yoy_badge(amazon_aov_val, amazon_aov_py_val, fmt_money, AMAZON_PY_DISPLAY))}
    </div>
  </div>
  <div class="section">
    {section_title('amazon', 'Sponsored Products · La Mend (US)', AMAZON_ADS_DISPLAY)}
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
      {card(fmt_money(amzs_rev_30, big=True), 'Ordered Revenue', f'<div class="sub">30-day total</div>' + (f'<div class="sub" style="padding-top:5px;border-top:0.5px solid #1f2937;margin-top:5px"><span style="color:#fbbf24">−{fmt_money(amazon_promo_30d)}</span> promo · <span style="color:#94a3b8">{fmt_pct(promo_pct_of_gross_30d)} of gross</span></div>' if amazon_promo_30d else ''))}
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

<div class="panel active" id="panel-0">
  <div class="summary-block">
    <div class="section">
      {section_title('activity', 'Performance Health', f'30-day blended · {T30_LABEL}')}
      <div class="cards-4">
        {card(fmt_money(total_sales_yest, big=True) if total_sales_yest else '—', 'Total Sales (Yesterday)', f'<div class="sub">{fmt_money(amazon_gross_yest)} Amazon · {fmt_money(shopify_net_yest)} Shopify</div>' + yoy_change_badge(yoy_pct_change, yoy_date_str, yoy_total))}
        {card(fmt_money(ncac_val) if ncac_val else '—', 'Shopify nCAC (yesterday)', (f'<div class="sub">spend ÷ {int(new_orders)} new Shopify orders</div>' if new_orders else '<div class="sub">no new orders</div>') + bm_ncac(ncac_val, shopify_aov_val))}
        {card(fmt_roas(mer_val), 'MER (Blended, 30d)', f'<div class="sub">{fmt_money(total_rev_30, big=True)} rev / {fmt_money(total_spend_30, big=True)} spend</div>' + bm_mer(mer_val))}
        {card(fmt_pct(new_rev_pct), 'New customer rev %', f'<div class="sub">{fmt_money(new_rev)} new / {fmt_money(new_rev + returning_rev)} total</div>' + bm_new_rev(new_rev_pct))}
      </div>
    </div>
    <div class="section">
      {section_title('users', 'Customer Health', '90-day rolling · Shopify only')}
      <div class="cards-4">
        {card(fmt_money(ltv_90) if ltv_90 else '—', 'LTV (90-day)', f'<div class="sub">{unique_customers_90:,} unique Shopify customers</div>')}
        {card(fmt_roas(ltv_cac_ratio) if ltv_cac_ratio else '—', 'LTV : CAC', f'<div class="sub">vs 30d Shopify nCAC of {fmt_money(ncac_30)}</div>' + bm_ltv_cac(ltv_cac_ratio))}
        {card(fmt_pct(rpr_90), 'Repeat purchase rate', f'<div class="sub">{repeat_customers:,} of {unique_customers_90:,} Shopify customers</div>' + bm_rpr(rpr_90))}
        {card(fmt_money(ncac_30) if ncac_30 else '—', 'Shopify nCAC (30-day avg)', f'<div class="sub">{int(new_orders_30):,} new / {fmt_money(dtc_spend_30, big=True)} DTC spend</div>')}
      </div>
    </div>
    {render_cohort_table()}
    <div class="section">
      {section_title('grid', 'SKU Affinity', 'First → second order · 6 months · Shopify')}
      <div class="sub" style="margin:-8px 0 12px;color:#94a3b8">For new customers who returned for a 2nd order, what was their original purchase and what did they buy next?</div>
      <table class="products">
        <thead><tr>
          <th>First-order product</th>
          <th class="prod-num">N customers</th>
          <th>Most common 2nd product</th>
          <th class="prod-num">% bought it</th>
          <th>Repeat rate</th>
        </tr></thead>
        <tbody>{sku_affinity_rows()}</tbody>
      </table>
    </div>
    <div class="section">
      {section_title('grid', 'Time Between Orders', '1st → 2nd order · 6 months · Shopify')}
      <div class="sub" style="margin:-8px 0 12px;color:#94a3b8">Of new customers who placed a 2nd order, how long did it take? Compressing this curve left = better email/SMS sequencing.</div>
      <div class="tbo-stats">
        <div class="tbo-stat"><div class="lbl">Median days to repeat</div><div class="val">{tbo_median}</div></div>
        <div class="tbo-stat"><div class="lbl">% repeating in 30d</div><div class="val">{tbo_pct_30*100:.0f}%</div></div>
        <div class="tbo-stat"><div class="lbl">% repeating in 90d</div><div class="val">{tbo_pct_90*100:.0f}%</div></div>
      </div>
      {tbo_histogram_bars()}
    </div>
    <div class="section">
      {section_title('grid', 'Top States by Total Revenue', f'Combined Shopify + Amazon · {T30_LABEL}')}
      <table class="products">
        <thead><tr>
          <th>State</th>
          <th class="prod-num">Total Revenue</th>
          <th class="prod-num">Shopify</th>
          <th class="prod-num">Amazon</th>
          <th>Share of Top 5</th>
        </tr></thead>
        <tbody>{combined_state_rows()}</tbody>
      </table>
    </div>
  </div>
</div>

<div class="panel" id="panel-2">
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
    {section_title('shopify', 'Top Product Variants by Revenue', T30_LABEL)}
    <table class="products">
      <thead><tr><th>Product Variant</th><th class="prod-num">Revenue</th><th class="prod-num">Units</th><th>Share of Top 5</th></tr></thead>
      <tbody>{shopify_variant_rows()}</tbody>
    </table>
  </div>
  {f'''<div class="section">
    {section_title('shopify', 'Site Conversion (GA4)', DISPLAY_DATE)}
    <div class="cards-4">
      {card(fmt_num(ga4_sessions, big=True), 'Sessions (yesterday)', '<div class="sub">from Google Analytics</div>')}
      {card(fmt_num(shopify_orders_yest), 'Orders', '<div class="sub">from Shopify</div>')}
      {card(fmt_pct(site_cvr_val), 'Site CVR (yesterday)', '<div class="sub">orders ÷ sessions</div>' + bm_cvr(site_cvr_val))}
      {card(fmt_pct(site_cvr_30), '30-Day Site CVR', f'<div class="sub">{fmt_num(ga4_sessions_30,big=True)} sessions total</div>' + bm_cvr(site_cvr_30))}
    </div>
  </div>''' if SHOW_GA4_SITE_CVR else ''}
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
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + i));
}}
window.addEventListener('load', () => {{
  {revenue_chart_js('amazonRevChart', amazon_chart_labels, amazon_chart_values, amazon_chart_avg7)}
  {sessions_cvr_chart_js('amazonSessChart', amazon_sess_labels, amazon_sess_values, amazon_cvr_values)}
  {revenue_chart_js('shopifyRevChart', shopify_chart_labels, shopify_chart_values, shopify_chart_avg7, 'Daily net sales')}
}});
</script>
</body>
</html>"""

with open("index.html", "w") as f:
    f.write(html)

print(f"Dashboard generated successfully for {DISPLAY_DATE}.")

# ── Slack post decision ────────────────────────────────────────────────────────
# Post to Slack if:
#   - Manual workflow trigger (always post), OR
#   - Haven't posted today yet AND (Amazon Ads has yesterday's data OR final attempt)
has_aa_data = bool(cache['daily'].get('amazon_ads', {}).get(DATE_STR))
already_posted = cache.get('last_posted_date') == DATE_STR
is_final_attempt = os.environ.get('IS_FINAL_ATTEMPT') == 'true'
is_manual = os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'

should_post = False
if is_manual or not already_posted:
    if has_aa_data or is_final_attempt or is_manual:
        should_post = True
        cache['last_posted_date'] = DATE_STR
        save_cache(cache)

print(f"  Amazon Ads for {DATE_STR}: {'OK' if has_aa_data else 'missing'}")
print(f"  Already posted today: {already_posted}")
print(f"  Final attempt (6am): {is_final_attempt}")
print(f"  Manual trigger: {is_manual}")
print(f"  -> Posting to Slack: {should_post}")

Path('should_post.flag').write_text('yes' if should_post else 'no')
