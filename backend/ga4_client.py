"""Pulls analytics either from a real GA4 property or from mock data.

Real mode uses the Google Analytics Data API (GA4) with a service-account
credential. If credentials/property are missing or USE_MOCK is on, it falls
back to mock_data so the app always works.
"""
from __future__ import annotations

from .config import settings
from . import mock_data


def _pct_change(curr: float, prev: float) -> float:
    if not prev:
        return 0.0
    return round((curr - prev) / prev * 100, 1)


def get_report(days: int = 28) -> dict:
    """Return a structured analytics report for the last `days` days."""
    if settings.USE_MOCK or not settings.ga4_ready:
        return mock_data.build_report(days)
    return _get_real_report(days)


# --------------------------------------------------------------------------
# Real GA4 implementation
# --------------------------------------------------------------------------
def _get_real_report(days: int) -> dict:
    # Imported lazily so the app runs in mock mode without the GA libs configured.
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Metric,
        RunReportRequest,
    )

    client = BetaAnalyticsDataClient()  # uses GOOGLE_APPLICATION_CREDENTIALS
    prop = f"properties/{settings.GA4_PROPERTY_ID}"

    curr_range = DateRange(start_date=f"{days}daysAgo", end_date="today")
    prev_range = DateRange(
        start_date=f"{days * 2}daysAgo", end_date=f"{days + 1}daysAgo"
    )

    metric_names = [
        "sessions",
        "totalUsers",
        "newUsers",
        "screenPageViews",
        "conversions",
        "engagementRate",
        "averageSessionDuration",
        "totalRevenue",
    ]

    # --- totals (current + previous period in one request) ----------------
    totals_req = RunReportRequest(
        property=prop,
        date_ranges=[curr_range, prev_range],
        metrics=[Metric(name=m) for m in metric_names],
    )
    totals_resp = client.run_report(totals_req)
    curr_vals, prev_vals = {}, {}
    for row in totals_resp.rows:
        bucket = curr_vals if row.dimension_values[0].value == "date_range_0" else prev_vals
        for i, m in enumerate(metric_names):
            bucket[m] = float(row.metric_values[i].value or 0)
    totals = {
        m: {
            "value": curr_vals.get(m, 0),
            "prev": prev_vals.get(m, 0),
            "change_pct": _pct_change(curr_vals.get(m, 0), prev_vals.get(m, 0)),
        }
        for m in metric_names
    }

    def _rows(dimension: str, metrics: list[str], limit: int = 10) -> list[dict]:
        req = RunReportRequest(
            property=prop,
            date_ranges=[curr_range],
            dimensions=[Dimension(name=dimension)],
            metrics=[Metric(name=m) for m in metrics],
            limit=limit,
        )
        resp = client.run_report(req)
        out = []
        for row in resp.rows:
            rec = {dimension: row.dimension_values[0].value}
            for i, m in enumerate(metrics):
                rec[m] = float(row.metric_values[i].value or 0)
            out.append(rec)
        return out

    channels = [
        {
            "channel": r["sessionDefaultChannelGroup"],
            "sessions": int(r["sessions"]),
            "conversions": int(r["conversions"]),
            "revenue": r["totalRevenue"],
        }
        for r in _rows(
            "sessionDefaultChannelGroup",
            ["sessions", "conversions", "totalRevenue"],
        )
    ]

    top_pages = [
        {
            "page": r["pagePath"],
            "views": int(r["screenPageViews"]),
            "avg_engagement_s": round(r["userEngagementDuration"] / max(r["screenPageViews"], 1), 1),
            "conversions": int(r["conversions"]),
        }
        for r in _rows(
            "pagePath",
            ["screenPageViews", "userEngagementDuration", "conversions"],
        )
    ]

    devices = []
    for r in _rows("deviceCategory", ["sessions", "conversions"]):
        sess = int(r["sessions"])
        conv = int(r["conversions"])
        devices.append(
            {
                "device": r["deviceCategory"],
                "sessions": sess,
                "conversions": conv,
                "conv_rate": round(conv / sess, 4) if sess else 0.0,
            }
        )

    top_countries = [
        {
            "country": r["country"],
            "sessions": int(r["sessions"]),
            "conversions": int(r["conversions"]),
        }
        for r in _rows("country", ["sessions", "conversions"])
    ]

    return {
        "period": {"days": days, "label": f"Last {days} days vs previous {days} days"},
        "totals": totals,
        "channels": channels,
        "top_pages": top_pages,
        "devices": devices,
        "top_countries": top_countries,
        "source": "ga4",
    }
