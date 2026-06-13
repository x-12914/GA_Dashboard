"""Turns an analytics report into ranked, revenue-focused suggestions.

Uses OpenAI or Claude when a key is set (see config.provider); otherwise falls
back to a built-in rule-based analyzer so the product is useful without a key.
"""
from __future__ import annotations

import json

from .config import settings

SYSTEM_PROMPT = """You are a senior growth/CRO analyst advising a small business \
owner who does NOT understand analytics. You are given a Google Analytics 4 \
report as JSON. Produce specific, prioritized, money-focused recommendations.

Rules:
- Tie every suggestion to revenue, conversions, or wasted spend where possible.
- Be concrete: name the exact page/channel/device and the number that proves it.
- No generic fluff ("improve your SEO"). Say WHAT to change and WHY.
- Rank by expected revenue impact.

Return ONLY valid JSON, no markdown, in exactly this shape:
{
  "summary": "2-3 sentence plain-English health check of the business",
  "suggestions": [
    {
      "title": "short imperative title",
      "priority": "high" | "medium" | "low",
      "category": "conversion" | "traffic" | "engagement" | "spend" | "revenue",
      "problem": "what the data shows, with the specific number",
      "action": "the exact thing to do this week",
      "expected_impact": "plausible upside if fixed"
    }
  ]
}"""


USER_PROMPT = "Here is the GA4 report:\n"

# The proven email is a FIXED template. Only the personalized opening hook is
# generated per store; the rest is the exact copy that's been sent and works.
COLD_EMAIL_BODY = (
    "I built a tool that connects to Google Analytics and pinpoints exactly where "
    "visitors are dropping off before they buy. If you're open to it, I'd happily run "
    "a quick, free analysis and show you the biggest opportunities — no obligation.\n\n"
    "Just reply and I'll send the details.\n\n"
    "Best,\n[Your Name]"
)

HOOK_SYSTEM = """You write the FIRST line of a cold email to a Shopify store owner, \
based on one concrete issue found on their store. Use exactly this pattern:

"I was looking through your store and noticed <specific, true observation>. That's usually <one plain reason it quietly costs sales>."

Rules:
- 1-2 sentences, under 45 words. Warm, human, plain — never salesy or jargony.
- Be specific to the given issue. NEVER invent a number or mention a "score";
  only cite a number if it appears in the issue text (e.g. a real PageSpeed score).
- Return ONLY those sentences — no subject, no greeting, no sign-off."""


def cold_email(audit: dict) -> dict:
    """Assemble the proven cold email: fixed template + one tailored hook line."""
    domain = _domain_of(audit.get("url", ""))
    store = (audit.get("store_name") or "").strip()
    greeting = f"Hi {store} team," if store else "Hi there,"

    provider = settings.provider
    engine = "template"
    hook = None
    if provider != "heuristic":
        try:
            hook = _hook_llm(audit, provider)
            engine = provider
        except Exception:
            hook = None
    if not hook:
        hook = _hook_template(audit)

    email = (f"Subject: quick note on {domain}\n\n"
             f"{greeting}\n\n{hook}\n\n{COLD_EMAIL_BODY}")
    return {"email": email, "engine": engine}


def _domain_of(url: str) -> str:
    return url.split("//")[-1].split("/")[0].replace("www.", "") if url else "your store"


def _top_issue_text(audit: dict) -> str:
    top = (audit.get("top_issues") or [None])[0]
    if not top:
        return "general conversion issues, nothing major broken"
    return f"{top['name']}: {top.get('detail', '')} {top.get('fix', '')}".strip()


def _hook_llm(audit: dict, provider: str) -> str:
    issue = _top_issue_text(audit)
    if provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "system", "content": HOOK_SYSTEM},
                      {"role": "user", "content": issue}],
        )
        return resp.choices[0].message.content.strip()
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=settings.ANTHROPIC_MODEL, max_tokens=200,
        system=HOOK_SYSTEM,
        messages=[{"role": "user", "content": issue}])
    return msg.content[0].text.strip()


def _hook_template(audit: dict) -> str:
    """No-LLM fallback hooks, matching the proven tone, for the common issues."""
    issues = audit.get("top_issues") or []
    top = issues[0] if issues else None
    if not top:
        return ("I was looking through your store and noticed a couple of small things "
                "that are likely costing you sales — the kind of quiet issues that lose "
                "first-time visitors before they buy.")
    name = top["name"].lower()
    if "reviews" in name:
        return ("I was looking through your store and noticed your product pages don't "
                "show any customer reviews. That's usually the single biggest thing "
                "quietly holding back sales — most shoppers won't buy without seeing that "
                "other people already did.")
    if "mobile speed" in name:
        detail = top.get("detail", "").split(":")[-1].strip().rstrip(".")
        return (f"I was looking through your store and noticed your mobile pages load "
                f"slowly ({detail}). That's usually where stores quietly lose visitors — "
                "most people leave before a slow page finishes loading.")
    if "email capture" in name:
        return ("I was looking through your store and noticed there's no email signup or "
                "popup. That's usually a quiet miss — most first-time visitors leave "
                "without buying, and email is how you bring them back.")
    if "social" in name:
        return ("I was looking through your store and noticed it doesn't link to any "
                "social profiles. That's usually a quiet miss — socials are social proof "
                "for new shoppers and a free traffic source you're leaving on the table.")
    if "trust" in name:
        return ("I was looking through your store and noticed it's light on trust signals "
                "(guarantees, free shipping, secure-checkout messaging). That's usually "
                "what quietly stops first-time buyers from checking out.")
    fix = (top.get("fix") or top.get("detail") or "").rstrip(".")
    return (f"I was looking through your store and noticed {name} — {fix}. That's usually "
            "the kind of small thing that quietly loses first-time visitors before they buy.")


def analyze(report: dict) -> dict:
    provider = settings.provider
    if provider == "heuristic":
        return _analyze_heuristic(report)
    try:
        if provider == "openai":
            return _analyze_with_openai(report)
        return _analyze_with_claude(report)
    except Exception as e:  # never let the AI path break the product
        result = _analyze_heuristic(report)
        result["summary"] = f"({provider} unavailable: {e}) " + result["summary"]
        return result


# --------------------------------------------------------------------------
def _analyze_with_openai(report: dict) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT + json.dumps(report, indent=2)},
        ],
    )
    data = json.loads(resp.choices[0].message.content)
    data["engine"] = f"openai:{settings.OPENAI_MODEL}"
    return data


# --------------------------------------------------------------------------
def _analyze_with_claude(report: dict) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": "Here is the GA4 report:\n" + json.dumps(report, indent=2),
            }
        ],
    )
    text = msg.content[0].text.strip()
    # Be tolerant if the model wraps JSON in a code fence.
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json").strip()
    data = json.loads(text)
    data["engine"] = f"claude:{settings.ANTHROPIC_MODEL}"
    return data


# --------------------------------------------------------------------------
def _analyze_heuristic(report: dict) -> dict:
    """A solid baseline so the app works with zero API keys."""
    suggestions: list[dict] = []
    totals = report.get("totals", {})

    # 1. Mobile vs desktop conversion gap -------------------------------
    devices = {d["device"]: d for d in report.get("devices", [])}
    mob, desk = devices.get("mobile"), devices.get("desktop")
    if mob and desk and desk["conv_rate"] > 0:
        ratio = mob["conv_rate"] / desk["conv_rate"]
        if ratio < 0.6 and mob["sessions"] > desk["sessions"] * 0.5:
            lost = int(mob["sessions"] * (desk["conv_rate"] - mob["conv_rate"]))
            suggestions.append({
                "title": "Fix the mobile conversion gap",
                "priority": "high",
                "category": "conversion",
                "problem": f"Mobile converts at {mob['conv_rate']*100:.2f}% vs desktop "
                           f"{desk['conv_rate']*100:.2f}% — yet mobile has "
                           f"{mob['sessions']:,} sessions (your biggest audience).",
                "action": "Audit the mobile checkout/signup flow: tap targets, form "
                          "length, page speed, and autofill. Test on a real phone.",
                "expected_impact": f"Closing half the gap could recover ~{lost:,} "
                                   "conversions per period.",
            })

    # 2. Leaky high-traffic, low-engagement pages -----------------------
    for p in report.get("top_pages", []):
        if p["views"] > 3000 and p["avg_engagement_s"] < 30 and p["conversions"] < p["views"] * 0.02:
            suggestions.append({
                "title": f"Plug the leak on {p['page']}",
                "priority": "high" if p["page"] in ("/checkout", "/signup") else "medium",
                "category": "conversion",
                "problem": f"{p['page']} gets {p['views']:,} views but only "
                           f"{p['avg_engagement_s']}s engagement and {p['conversions']} "
                           "conversions — people land and bounce.",
                "action": "Clarify the headline + primary CTA above the fold, remove "
                          "distractions, and make the next step obvious.",
                "expected_impact": "High-traffic pages give the fastest ROI on CRO fixes.",
            })

    # 3. Paid spend with weak return ------------------------------------
    channels = {c["channel"]: c for c in report.get("channels", [])}
    for name in ("Paid Social", "Paid Search"):
        c = channels.get(name)
        if c and c["sessions"] > 1500:
            cps = c["revenue"] / c["sessions"] if c["sessions"] else 0
            conv_rate = c["conversions"] / c["sessions"] if c["sessions"] else 0
            if conv_rate < 0.01:
                suggestions.append({
                    "title": f"Re-think {name} spend",
                    "priority": "medium",
                    "category": "spend",
                    "problem": f"{name} drove {c['sessions']:,} sessions but only "
                               f"{c['conversions']} conversions "
                               f"({conv_rate*100:.2f}%) and ${c['revenue']:,.0f} revenue.",
                    "action": "Pause weakest ad sets, tighten targeting, and send traffic "
                              "to a dedicated landing page that matches the ad promise.",
                    "expected_impact": "Reallocating budget to your best channel lifts "
                                       "overall ROAS.",
                })

    # 4. Under-used best channel ----------------------------------------
    best = max(channels.values(), key=lambda c: (c["conversions"] / c["sessions"]) if c["sessions"] else 0, default=None)
    if best and best["sessions"] < 5000:
        suggestions.append({
            "title": f"Pour more into {best['channel']}",
            "priority": "medium",
            "category": "traffic",
            "problem": f"{best['channel']} is your most efficient channel "
                       f"({best['conversions']} conversions from {best['sessions']:,} "
                       "sessions) but gets relatively little traffic.",
            "action": "Double down: more content/budget/effort on this channel since it "
                      "already converts best.",
            "expected_impact": "Scaling a proven channel is lower-risk than chasing new ones.",
        })

    # 5. Falling conversions / revenue ----------------------------------
    conv = totals.get("conversions", {})
    rev = totals.get("totalRevenue", {})
    if conv.get("change_pct", 0) < -3:
        suggestions.append({
            "title": "Reverse the conversion decline",
            "priority": "high",
            "category": "revenue",
            "problem": f"Conversions are down {abs(conv['change_pct'])}% and revenue "
                       f"{('down ' + str(abs(rev.get('change_pct', 0))) + '%') if rev.get('change_pct', 0) < 0 else 'flat'} "
                       "vs the previous period, even though sessions grew.",
            "action": "You're getting more visitors but converting fewer — focus the week "
                      "entirely on the funnel, not on more traffic.",
            "expected_impact": "Restoring last period's rate recovers lost revenue directly.",
        })

    order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda s: order.get(s["priority"], 3))

    sess = totals.get("sessions", {}).get("value", 0)
    summary = (
        f"You had {sess:,.0f} sessions this period. Traffic is "
        f"{'up' if totals.get('sessions', {}).get('change_pct', 0) >= 0 else 'down'}, "
        "but conversions are the weak point — the biggest wins are in your funnel, "
        "not in getting more visitors. Top priorities are listed below."
    )

    return {"summary": summary, "suggestions": suggestions, "engine": "heuristic"}
