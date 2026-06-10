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

COLD_EMAIL_SYSTEM = """You write short, friendly cold outreach emails to Shopify \
store owners. You are given a public audit of their store. Write an email that:
- Opens with ONE specific, true observation from the audit (builds credibility).
- Lists their top 2-3 issues as quick wins, in plain language, no jargon.
- Offers a free deeper look once they connect their Google Analytics.
- Is under 120 words, warm, not salesy, with a clear soft CTA.
Return ONLY the email body as plain text (no subject line, no markdown)."""


def cold_email(audit: dict) -> dict:
    """Generate a ready-to-send cold email from a store audit."""
    provider = settings.provider
    if provider != "heuristic":
        try:
            body = _cold_email_llm(audit, provider)
            return {"email": body, "engine": provider}
        except Exception:
            pass
    return {"email": _cold_email_template(audit), "engine": "template"}


def _cold_email_llm(audit: dict, provider: str) -> str:
    payload = json.dumps(
        {"url": audit.get("url"), "score": audit.get("score"),
         "issues": audit.get("top_issues", [])}, indent=2)
    if provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "system", "content": COLD_EMAIL_SYSTEM},
                      {"role": "user", "content": payload}],
        )
        return resp.choices[0].message.content.strip()
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=settings.ANTHROPIC_MODEL, max_tokens=500,
        system=COLD_EMAIL_SYSTEM,
        messages=[{"role": "user", "content": payload}])
    return msg.content[0].text.strip()


def _cold_email_template(audit: dict) -> str:
    issues = audit.get("top_issues", [])
    lines = [f"  • {c['name']}: {c['fix'] or c['detail']}" for c in issues[:3]]
    bullets = "\n".join(lines) if lines else "  • A few quick conversion wins"
    return (
        "Hi there,\n\n"
        "I was looking at your store and noticed a few quick things that are likely "
        "costing you sales:\n\n"
        f"{bullets}\n\n"
        "These are just what I can see from the outside. If you connect your Google "
        "Analytics (takes 2 minutes), I'll send you a free breakdown of exactly where "
        "in your funnel you're losing buyers — no charge, no commitment.\n\n"
        "Want me to send it over?\n\n"
        "Best,\n[Your name]"
    )


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
