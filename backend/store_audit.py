"""Public Shopify store auditor — needs ZERO access to the store.

Given a public URL it fetches the storefront HTML (and optionally Google
PageSpeed Insights) and reports fixable, revenue-relevant issues. This is the
cold-outreach engine: every finding is verifiably true about *their* store.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .config import settings

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Signatures of common Shopify apps / patterns, grouped by what they prove.
REVIEW_APPS = ["judge.me", "yotpo", "stamped", "loox", "okendo", "reviews.io",
               "shopify-product-reviews", "fera.ai", "ryviu"]
EMAIL_APPS = ["klaviyo", "privy", "mailchimp", "omnisend", "justuno", "sumo"]
TRUST_WORDS = ["money-back", "money back", "satisfaction guarantee", "secure checkout",
               "free shipping", "free returns", "30-day", "ssl", "trusted"]
URGENCY_WORDS = ["only", "left in stock", "selling fast", "limited", "ends in", "hurry"]
SOCIAL_DOMAINS = {
    "facebook.com": "Facebook", "instagram.com": "Instagram", "tiktok.com": "TikTok",
    "twitter.com": "X/Twitter", "x.com": "X/Twitter", "youtube.com": "YouTube",
    "pinterest.com": "Pinterest", "linkedin.com": "LinkedIn",
}


def _check(name, status, detail, fix=""):
    return {"name": name, "status": status, "detail": detail, "fix": fix}


# --------------------------------------------------------------------------
# Structured data (schema.org) helpers
# --------------------------------------------------------------------------
def _iter_jsonld(data):
    """Yield each schema object from a parsed JSON-LD blob (handles @graph/lists)."""
    if isinstance(data, dict):
        if isinstance(data.get("@graph"), list):
            for x in data["@graph"]:
                yield from _iter_jsonld(x)
        else:
            yield data
    elif isinstance(data, list):
        for x in data:
            yield from _iter_jsonld(x)


def _schema_types(soup) -> set:
    """Collect all schema.org @type values present (JSON-LD + microdata)."""
    types: set[str] = set()
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for obj in _iter_jsonld(data):
            t = obj.get("@type")
            if isinstance(t, list):
                types.update(str(x) for x in t)
            elif isinstance(t, str):
                types.add(t)
    for el in soup.find_all(attrs={"itemtype": True}):
        it = el.get("itemtype", "")
        if "schema.org" in it:
            types.add(it.rstrip("/").split("/")[-1])
    return types


def audit(url: str) -> dict:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        with httpx.Client(follow_redirects=True, timeout=15.0,
                          headers={"User-Agent": UA}) as client:
            resp = client.get(url)
            html = resp.text
            final_url = str(resp.url)
            status_code = resp.status_code
    except Exception as e:
        return {"url": url, "ok": False, "error": f"Could not fetch the site: {e}",
                "checks": [], "score": 0}

    soup = BeautifulSoup(html, "html.parser")
    text_low = html.lower()
    page_bytes = len(html.encode("utf-8", errors="ignore"))

    checks: list[dict] = []

    # --- Is it Shopify? -------------------------------------------------
    is_shopify = any(s in text_low for s in
                     ["cdn.shopify.com", "myshopify.com", "shopify.theme", "x-shopify"])

    # --- Reviews / social proof ----------------------------------------
    has_reviews = any(a in text_low for a in REVIEW_APPS) or "star" in text_low and "rating" in text_low
    checks.append(_check(
        "Product reviews / social proof",
        "good" if has_reviews else "bad",
        "Review widget detected." if has_reviews
        else "No review/ratings app detected on the page.",
        "" if has_reviews else
        "Add reviews (Judge.me / Loox). Stores with reviews convert noticeably better — "
        "shoppers don't buy without social proof.",
    ))

    # --- Email capture --------------------------------------------------
    has_email = (any(a in text_low for a in EMAIL_APPS)
                 or bool(soup.find("input", {"type": "email"}))
                 or "newsletter" in text_low or "subscribe" in text_low)
    checks.append(_check(
        "Email capture",
        "good" if has_email else "bad",
        "Email signup / popup detected." if has_email
        else "No newsletter signup or popup found.",
        "" if has_email else
        "Add an email popup (Klaviyo/Privy) with a small discount. Most first-time "
        "visitors leave without buying — email is how you win them back.",
    ))

    # --- Trust signals --------------------------------------------------
    trust_hits = [w for w in TRUST_WORDS if w in text_low]
    checks.append(_check(
        "Trust signals",
        "good" if len(trust_hits) >= 2 else ("warn" if trust_hits else "bad"),
        f"Found: {', '.join(sorted(set(trust_hits)))}." if trust_hits
        else "No guarantee / free-shipping / secure-checkout messaging found.",
        "" if len(trust_hits) >= 2 else
        "Add visible guarantees (money-back, free shipping/returns, secure checkout). "
        "These reduce the fear that stops purchases.",
    ))

    # --- Urgency / scarcity --------------------------------------------
    has_urgency = any(w in text_low for w in URGENCY_WORDS)
    checks.append(_check(
        "Urgency / scarcity",
        "good" if has_urgency else "warn",
        "Urgency messaging detected." if has_urgency
        else "No scarcity/urgency cues found.",
        "" if has_urgency else
        "Add subtle urgency (low-stock counts, limited offers) to nudge fence-sitters.",
    ))

    # --- SEO basics -----------------------------------------------------
    title = (soup.title.string or "").strip() if soup.title else ""
    meta_desc = soup.find("meta", attrs={"name": "description"})
    desc = (meta_desc.get("content") or "").strip() if meta_desc else ""
    seo_ok = bool(title) and bool(desc)
    checks.append(_check(
        "SEO basics (title + description)",
        "good" if seo_ok else "warn",
        f"Title: {'set' if title else 'MISSING'}; "
        f"meta description: {'set' if desc else 'MISSING'}.",
        "" if seo_ok else
        "Add a descriptive page title and meta description so Google sends you free "
        "traffic and the search listing looks clickable.",
    ))

    # --- Page weight (proxy for speed) ---------------------------------
    scripts = len(soup.find_all("script"))
    imgs = soup.find_all("img")
    lazy = sum(1 for i in imgs if i.get("loading") == "lazy")
    heavy = page_bytes > 600_000 or scripts > 35
    checks.append(_check(
        "Page weight / speed (HTML proxy)",
        "warn" if heavy else "good",
        f"HTML {page_bytes // 1024} KB, {scripts} scripts, "
        f"{lazy}/{len(imgs)} images lazy-loaded.",
        "Trim apps/scripts and lazy-load images. Slow mobile pages lose ~40% of "
        "visitors before they ever see your products." if heavy else "",
    ))

    # --- Structured data / rich snippets (schema.org) ------------------
    schema_types = _schema_types(soup)
    key_schema = {"Product", "Organization", "WebSite", "BreadcrumbList", "Store"}
    has_key_schema = bool(schema_types & key_schema)
    checks.append(_check(
        "Structured data (schema.org)",
        "good" if has_key_schema else "warn",
        f"Found: {', '.join(sorted(schema_types)[:6])}." if schema_types
        else "No schema.org structured data found.",
        "" if has_key_schema else
        "Add structured data (Organization, Product, Breadcrumb) so Google can show "
        "rich results — logo, sitelinks, star ratings. More clicks from the same ranking.",
    ))

    # --- Image alt-text coverage ---------------------------------------
    if len(imgs) >= 5:
        with_alt = sum(1 for i in imgs if (i.get("alt") or "").strip())
        cov = with_alt / len(imgs)
        checks.append(_check(
            "Image alt text",
            "good" if cov >= 0.7 else ("warn" if cov >= 0.4 else "bad"),
            f"{with_alt}/{len(imgs)} images have alt text ({round(cov * 100)}%).",
            "" if cov >= 0.7 else
            "Add descriptive alt text to product images — Google Images sends free "
            "buyer traffic, and it improves accessibility.",
        ))

    # --- Social media presence -----------------------------------------
    social_found = set()
    for a in soup.find_all("a", href=True):
        h = a["href"].lower()
        for dom, name in SOCIAL_DOMAINS.items():
            if dom in h:
                social_found.add(name)
    checks.append(_check(
        "Social media presence",
        "good" if len(social_found) >= 2 else ("warn" if social_found else "bad"),
        f"Linked: {', '.join(sorted(social_found))}." if social_found
        else "No social media links found.",
        "" if len(social_found) >= 2 else
        "Link your active social profiles — they're social proof and a free traffic / "
        "retargeting source.",
    ))

    # --- Blog / content presence ---------------------------------------
    has_blog = bool(soup.find("a", href=lambda h: h and ("/blogs" in h or "/blog" in h)))
    checks.append(_check(
        "Blog / content",
        "good" if has_blog else "warn",
        "Blog / content section found." if has_blog
        else "No blog or content section detected.",
        "" if has_blog else
        "Add a blog. Content earns free Google traffic and builds trust before the sale.",
    ))

    # --- Product page deep-dive (where conversion is won/lost) ----------
    product_url = _find_product_url(soup, final_url)
    if product_url:
        checks.extend(_product_page_checks(product_url))

    # NOTE: Mobile speed (Google PageSpeed) is fetched separately via
    # pagespeed_check() / the /api/pagespeed endpoint, because PSI can take
    # 30-120s and must not block this fast audit.

    good = sum(1 for c in checks if c["status"] == "good")
    warn = sum(1 for c in checks if c["status"] == "warn")
    total = len(checks) or 1
    score = round(100 * (good + 0.5 * warn) / total)  # proportional, scales with checks

    # Lead with the most serious issues (bad before warn) for the cold email.
    issues = ([c for c in checks if c["status"] == "bad"]
              + [c for c in checks if c["status"] == "warn"])

    return {
        "url": final_url,
        "ok": True,
        "is_shopify": is_shopify,
        "status_code": status_code,
        "product_url": product_url,
        "score": score,
        "checks": checks,
        "top_issues": issues[:3],
    }


def _find_product_url(soup, base_url):
    """Find the first product page link on the homepage (Shopify uses /products/)."""
    for a in soup.find_all("a", href=True):
        if "/products/" in a["href"]:
            return urljoin(base_url, a["href"].split("?")[0])
    return None


def _product_page_checks(product_url: str) -> list:
    """Fetch a real product page and run conversion checks on it."""
    try:
        with httpx.Client(follow_redirects=True, timeout=15.0,
                          headers={"User-Agent": UA}) as client:
            html = client.get(product_url).text
    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")
    low = html.lower()
    checks = []

    # Reviews matter MOST on the product page — that's the buy decision.
    has_rev = (any(a in low for a in REVIEW_APPS)
               or ("review" in low and ("star" in low or "rating" in low)))
    checks.append(_check(
        "Product page — reviews",
        "good" if has_rev else "bad",
        "Reviews/ratings present on the product page." if has_rev
        else "No reviews on the product page itself.",
        "" if has_rev else
        "Reviews matter most on the product page — that's where people decide. Add them here.",
    ))

    # Clear add-to-cart.
    has_atc = ("add to cart" in low or "add_to_cart" in low
               or 'name="add"' in low or "/cart/add" in low)
    checks.append(_check(
        "Product page — add to cart",
        "good" if has_atc else "warn",
        "Add-to-cart action detected." if has_atc
        else "Couldn't clearly detect an add-to-cart button.",
        "" if has_atc else
        "Make the add-to-cart button obvious and above the fold.",
    ))

    # Multiple product photos build buying confidence.
    n_imgs = len(soup.find_all("img"))
    checks.append(_check(
        "Product page — images",
        "good" if n_imgs >= 3 else "warn",
        f"{n_imgs} images on the product page.",
        "" if n_imgs >= 3 else
        "Add multiple photos (angles, in-use, scale). More images = more confidence = more sales.",
    ))

    # Product schema → price + stars in Google results (big CTR lift).
    has_product_schema = "Product" in _schema_types(soup)
    checks.append(_check(
        "Product page — rich snippets (Product schema)",
        "good" if has_product_schema else "warn",
        "Product structured data present (can show price/stars in Google)." if has_product_schema
        else "No Product schema found on the product page.",
        "" if has_product_schema else
        "Add Product structured data so Google can show price and star ratings in search "
        "— a big click-through boost.",
    ))

    return checks


def pagespeed_check(url: str):
    """Return a 'Mobile speed' check dict from PageSpeed, or None if unavailable.

    Called separately from audit() so the slow PSI request never blocks the
    fast audit. Returns None when no key is set or the site is too slow/heavy
    for PSI to analyze in time.
    """
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    psi = _pagespeed(url)
    if psi is None:
        return None
    perf = psi["perf"]
    return _check(
        "Mobile speed (Google PageSpeed)",
        "bad" if perf < 50 else ("warn" if perf < 80 else "good"),
        f"Google mobile performance score: {perf}/100"
        + (f", largest paint {psi['lcp']}." if psi.get("lcp") else "."),
        "Speed up mobile (image sizes, fewer apps, faster theme). Google data ties "
        "slow load directly to lost sales." if perf < 80 else "",
    )


# --------------------------------------------------------------------------
# Contact email extraction (kills the "find the owner's email" time-sink)
# --------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Pages most likely to expose a real contact email on a Shopify store.
_EMAIL_PATHS = ["", "/pages/contact", "/pages/contact-us", "/pages/about",
                "/policies/refund-policy", "/policies/privacy-policy",
                "/policies/contact-information"]
# Junk that the email regex picks up but isn't a real contact address.
_EMAIL_NOISE = ("sentry", "wixpress", "example.", "godaddy", "@2x", ".png", ".jpg",
                ".gif", ".webp", ".svg", "@sentry.io", "your-email", "email@",
                "domain.com", "test@", "@test.", "noreply", "no-reply", "@email.com",
                "you@", "name@", "user@", "username@", "yourdomain", "yourstore",
                "@company.com", "sentry.wixpress", "core@", "@example")
_EMAIL_PREFIX_RANK = ["hello@", "contact@", "support@", "care@", "info@",
                      "sales@", "team@", "help@"]


def extract_email(url: str):
    """Best-effort: find a public contact email by scanning a store's key pages.

    Prefers addresses on the store's own domain, then common contact prefixes.
    Returns the single best email, or None.
    """
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    site_domain = urlparse(url).netloc.lower().replace("www.", "")

    found: set[str] = set()
    try:
        with httpx.Client(follow_redirects=True, timeout=12.0,
                          headers={"User-Agent": UA}) as client:
            for path in _EMAIL_PATHS:
                try:
                    r = client.get(url + path)
                except Exception:
                    continue
                if r.status_code >= 400:
                    continue
                for m in _EMAIL_RE.findall(r.text):
                    e = m.lower().strip(".")
                    if not any(n in e for n in _EMAIL_NOISE):
                        found.add(e)
                # Stop early once we have a same-domain address.
                if any(e.endswith("@" + site_domain) for e in found):
                    break
    except Exception:
        return None

    if not found:
        return None

    def rank(e: str):
        same = e.endswith("@" + site_domain)
        prefix_rank = next((i for i, p in enumerate(_EMAIL_PREFIX_RANK)
                            if e.startswith(p)), len(_EMAIL_PREFIX_RANK))
        return (0 if same else 1, prefix_rank, len(e))

    return sorted(found, key=rank)[0]


# --------------------------------------------------------------------------
# Store discovery via Google Programmable Search (optional)
# --------------------------------------------------------------------------
_DISCOVERY_EXCLUDE = (
    "shopify.com", "myshopify.com", "amazon.", "ebay.", "etsy.", "aliexpress.",
    "walmart.", "instagram.com", "facebook.com", "tiktok.com", "youtube.com",
    "pinterest.com", "twitter.com", "x.com", "linkedin.com", "reddit.com",
    "wikipedia.org", "google.", "trustpilot.", "yelp.", "apps.shopify",
)


def discover_stores(niche: str, limit: int = 20) -> list[str]:
    """Find candidate store domains for a niche via Google Custom Search.

    Returns a deduped list of domains (not full URLs). Empty list if discovery
    isn't configured. The caller still audits each to confirm it's Shopify.
    """
    if not settings.discovery_ready or not niche.strip():
        return []
    key, cx = settings.cse_key, settings.GOOGLE_CSE_ID
    queries = [
        f'{niche} "powered by shopify"',
        f'{niche} shopify store',
        f'{niche} inurl:collections',
    ]
    domains: list[str] = []
    seen: set[str] = set()
    try:
        with httpx.Client(timeout=20.0) as client:
            for q in queries:
                for start in (1, 11):  # 2 pages per query = up to 20 results
                    if len(domains) >= limit:
                        break
                    r = client.get(
                        "https://www.googleapis.com/customsearch/v1",
                        params={"key": key, "cx": cx, "q": q, "num": 10, "start": start},
                    )
                    if r.status_code != 200:
                        break
                    items = r.json().get("items", [])
                    if not items:
                        break
                    for it in items:
                        dom = urlparse(it.get("link", "")).netloc.lower().replace("www.", "")
                        if dom and dom not in seen and not any(x in dom for x in _DISCOVERY_EXCLUDE):
                            seen.add(dom)
                            domains.append(dom)
                if len(domains) >= limit:
                    break
    except Exception:
        return domains[:limit]
    return domains[:limit]


def _pagespeed(url: str):
    """Call Google PageSpeed Insights if a key is configured; else skip."""
    key = settings.PAGESPEED_API_KEY
    if not key:
        return None
    try:
        params = {"url": url, "strategy": "mobile", "key": key, "category": "performance"}
        # PageSpeed loads the page in a real browser — heavy stores can take 40s+.
        with httpx.Client(timeout=55.0) as client:
            r = client.get(
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                params=params,
            )
            data = r.json()
        lh = data["lighthouseResult"]
        perf = round(lh["categories"]["performance"]["score"] * 100)
        lcp = lh["audits"].get("largest-contentful-paint", {}).get("displayValue")
        return {"perf": perf, "lcp": lcp}
    except Exception:
        return None
