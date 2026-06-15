"""Prospect Finder — turn a niche or a list of URLs into ranked, ready-to-contact
Shopify prospects.

For each candidate it: audits the store, grabs a contact email, scores how good
a prospect it is (low health + clear hook + reachable = better), and surfaces
the single best hook. Runs audits concurrently so a batch takes seconds.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as _FTimeout

from . import store_audit


def _prospect_score(audit: dict, email: str | None) -> int:
    """Higher = better prospect. Favors real Shopify stores with clear,
    fixable gaps that we can actually reach by email."""
    if not audit.get("ok"):
        return -1
    score = 0
    if audit.get("is_shopify"):
        score += 40  # only really pitch Shopify stores
    # Lower store health = more to fix = stronger pitch (cap the contribution).
    score += max(0, 100 - audit.get("score", 100)) // 2
    checks = audit.get("checks", [])
    bad = sum(1 for c in checks if c["status"] == "bad")
    score += bad * 6
    # The strongest hooks specifically:
    for c in checks:
        if c["status"] == "bad" and c["name"].startswith("Product reviews"):
            score += 12
        if c["status"] in ("bad", "warn") and "Mobile speed" in c["name"]:
            score += 6
    if email:
        score += 15  # reachable beats not-reachable
    return score


def _best_hook(audit: dict) -> dict | None:
    issues = audit.get("top_issues") or []
    return issues[0] if issues else None


def _evaluate(target: str, want_email: bool) -> dict | None:
    audit = store_audit.audit(target)
    if not audit.get("ok"):
        return None
    email = store_audit.extract_email(audit["url"]) if want_email else None
    hook = _best_hook(audit)
    return {
        "url": audit["url"],
        "domain": audit["url"].split("//")[-1].split("/")[0].replace("www.", ""),
        "is_shopify": audit.get("is_shopify", False),
        "score": audit.get("score", 0),
        "email": email,
        "best_hook": hook,
        "bad_count": sum(1 for c in audit["checks"] if c["status"] == "bad"),
        "checks": audit["checks"],
        "prospect_score": _prospect_score(audit, email),
    }


def find_prospects(targets: list[str], want_email: bool = True,
                   shopify_only: bool = True, overall_timeout: float = 70.0) -> list[dict]:
    """Audit + email-extract + rank a list of store URLs/domains, concurrently.

    Bounded by overall_timeout: returns whatever finished by the deadline so a
    single slow store can never hang the whole request (which would time out at
    nginx and return an HTML error page to the browser).
    """
    targets = [t.strip() for t in targets if t.strip()][:15]  # safety cap
    if not targets:
        return []
    ex = ThreadPoolExecutor(max_workers=8)
    futures = [ex.submit(_evaluate, t, want_email) for t in targets]
    results: list[dict] = []
    try:
        for fut in as_completed(futures, timeout=overall_timeout):
            try:
                r = fut.result()
            except Exception:
                r = None
            if r:
                results.append(r)
    except _FTimeout:
        pass  # deadline hit — keep what finished, drop the stragglers
    ex.shutdown(wait=False, cancel_futures=True)
    if shopify_only:
        results = [r for r in results if r["is_shopify"]]
    results.sort(key=lambda r: r["prospect_score"], reverse=True)
    return results
