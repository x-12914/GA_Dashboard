"""Public Shopify store auditor — needs ZERO access to the store.

Given a public URL it fetches the storefront HTML (and optionally Google
PageSpeed Insights) and reports fixable, revenue-relevant issues. This is the
cold-outreach engine: every finding is verifiably true about *their* store.
"""
from __future__ import annotations

import re

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


def _check(name, status, detail, fix=""):
    return {"name": name, "status": status, "detail": detail, "fix": fix}


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

    # --- Real speed via PageSpeed Insights (optional) ------------------
    psi = _pagespeed(final_url)
    if psi is not None:
        slow = psi["perf"] < 50
        checks.append(_check(
            "Mobile speed (Google PageSpeed)",
            "bad" if slow else ("warn" if psi["perf"] < 80 else "good"),
            f"Google mobile performance score: {psi['perf']}/100"
            + (f", largest paint {psi['lcp']}." if psi.get("lcp") else "."),
            "Speed up mobile (image sizes, fewer apps, faster theme). Google data ties "
            "slow load directly to lost sales." if psi["perf"] < 80 else "",
        ))

    bad = sum(1 for c in checks if c["status"] == "bad")
    warn = sum(1 for c in checks if c["status"] == "warn")
    score = max(0, 100 - bad * 18 - warn * 7)

    return {
        "url": final_url,
        "ok": True,
        "is_shopify": is_shopify,
        "status_code": status_code,
        "score": score,
        "checks": checks,
        "top_issues": [c for c in checks if c["status"] in ("bad", "warn")][:3],
    }


def _pagespeed(url: str):
    """Call Google PageSpeed Insights if a key is configured; else skip."""
    key = settings.PAGESPEED_API_KEY
    if not key:
        return None
    try:
        params = {"url": url, "strategy": "mobile", "key": key, "category": "performance"}
        with httpx.Client(timeout=30.0) as client:
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
