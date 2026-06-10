"""Realistic mock analytics so the whole pipeline works before GA4 is connected.

The numbers are intentionally "imperfect" — they contain a few obvious
problems (mobile conversion drop, a leaky checkout page, an over-reliance on
paid traffic) so the analyzer has something real to react to.
"""
from __future__ import annotations


def build_report(days: int = 28) -> dict:
    """Return a structured analytics report matching the GA4 client output."""
    return {
        "period": {"days": days, "label": f"Last {days} days vs previous {days} days"},
        "totals": {
            "sessions": {"value": 18432, "prev": 16980, "change_pct": 8.6},
            "totalUsers": {"value": 12010, "prev": 11220, "change_pct": 7.0},
            "newUsers": {"value": 8740, "prev": 8050, "change_pct": 8.6},
            "screenPageViews": {"value": 51200, "prev": 49100, "change_pct": 4.3},
            "conversions": {"value": 286, "prev": 312, "change_pct": -8.3},
            "engagementRate": {"value": 0.512, "prev": 0.547, "change_pct": -6.4},
            "averageSessionDuration": {"value": 92.4, "prev": 101.7, "change_pct": -9.1},
            "totalRevenue": {"value": 21450.0, "prev": 23010.0, "change_pct": -6.8},
        },
        "channels": [
            {"channel": "Paid Search", "sessions": 7100, "conversions": 78, "revenue": 6900.0},
            {"channel": "Organic Search", "sessions": 4300, "conversions": 96, "revenue": 8800.0},
            {"channel": "Direct", "sessions": 3100, "conversions": 61, "revenue": 3650.0},
            {"channel": "Paid Social", "sessions": 2600, "conversions": 19, "revenue": 1100.0},
            {"channel": "Referral", "sessions": 900, "conversions": 22, "revenue": 800.0},
            {"channel": "Email", "sessions": 432, "conversions": 10, "revenue": 200.0},
        ],
        "top_pages": [
            {"page": "/", "views": 14200, "avg_engagement_s": 38, "conversions": 41},
            {"page": "/pricing", "views": 6100, "avg_engagement_s": 71, "conversions": 88},
            {"page": "/blog/how-to-grow", "views": 5400, "avg_engagement_s": 142, "conversions": 5},
            {"page": "/product", "views": 4800, "avg_engagement_s": 64, "conversions": 52},
            {"page": "/checkout", "views": 3900, "avg_engagement_s": 28, "conversions": 76},
            {"page": "/signup", "views": 3200, "avg_engagement_s": 22, "conversions": 24},
        ],
        "devices": [
            {"device": "mobile", "sessions": 11050, "conversions": 92, "conv_rate": 0.0083},
            {"device": "desktop", "sessions": 6200, "conversions": 178, "conv_rate": 0.0287},
            {"device": "tablet", "sessions": 1182, "conversions": 16, "conv_rate": 0.0135},
        ],
        "top_countries": [
            {"country": "United States", "sessions": 9800, "conversions": 171},
            {"country": "United Kingdom", "sessions": 2300, "conversions": 38},
            {"country": "Canada", "sessions": 1700, "conversions": 29},
            {"country": "Germany", "sessions": 1400, "conversions": 14},
            {"country": "India", "sessions": 3232, "conversions": 34},
        ],
        "source": "mock",
    }
