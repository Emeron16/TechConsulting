"""Generates a synthetic TrueBlue loyalty member dataset for churn model
development, standing in for the Redshift/S3 member-level extract that
would normally be produced by the PySpark consolidation job described in
Section 2 of notebooks/trublue_churn_model.ipynb.

Covers booking behavior, points earning/redemption, route and fare
patterns, seasonal travel behavior, customer support interactions,
promotion response, digital engagement, and RFM rollups — i.e. every
feature category called out in Section 5 (Feature Engineering) of the
notebook. Also emits a churn_label column derived from a weighted risk
score (not pure noise), so the "signal" columns actually correlate with
the target the way they would in a real loyalty dataset.

Usage: python scripts/generate_synthetic_members.py
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

N_MEMBERS = 1200
OUTPUT_PATH = (
    Path(__file__).parent.parent / "data" / "synthetic_members" / "trublue_churn_dataset.csv"
)
SNAPSHOT_DATE = date(2026, 8, 24)

TIERS = ["Mosaic", "Blue Plus", "Blue"]
TIER_WEIGHTS = [0.08, 0.27, 0.65]

HUBS = ["JFK", "BOS", "FLL", "MCO", "LAX", "SJU", "JFK", "BOS"]  # JFK/BOS weighted heavier

FARE_CLASSES = ["Blue Basic", "Blue", "Blue Extra", "Mint"]
FARE_CLASS_WEIGHTS = [0.30, 0.40, 0.22, 0.08]


def sample_tier() -> str:
    return random.choices(TIERS, weights=TIER_WEIGHTS, k=1)[0]


def sample_enrollment_date() -> date:
    days_ago = random.randint(30, 365 * 12)
    return SNAPSHOT_DATE - timedelta(days=days_ago)


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def generate_member(member_id: int) -> dict:
    tier = sample_tier()
    enrollment_dt = sample_enrollment_date()
    tenure_days = (SNAPSHOT_DATE - enrollment_dt).days

    # Latent, unobserved "true" engagement level driving most other fields —
    # mimics how real members cluster into engaged / lapsing / dormant groups
    # rather than every feature being drawn independently at random.
    engagement = clamp(random.gauss(0.55, 0.25), 0.0, 1.0)
    if tier == "Mosaic":
        engagement = clamp(engagement + 0.25, 0.0, 1.0)
    elif tier == "Blue Plus":
        engagement = clamp(engagement + 0.10, 0.0, 1.0)

    # --- Booking behavior / recency --------------------------------------
    days_since_last_booking = int(clamp(random.expovariate(1 / (20 + (1 - engagement) * 300)), 1, 900))
    bookings_last_90d = max(0, int(random.gauss(engagement * 3, 1.2)))
    bookings_last_180d = bookings_last_90d + max(0, int(random.gauss(engagement * 2.5, 1.5)))
    bookings_last_365d = bookings_last_180d + max(0, int(random.gauss(engagement * 3, 2)))
    total_bookings_lifetime = bookings_last_365d + max(
        0, int(random.gauss(engagement * (tenure_days / 180), 5))
    )

    # --- Monetary / fare patterns -----------------------------------------
    avg_fare = round(clamp(random.gauss(180 + engagement * 220, 60), 59, 1200), 2)
    total_spend_lifetime = round(avg_fare * max(total_bookings_lifetime, 1) * random.uniform(0.85, 1.15), 2)
    fare_class = random.choices(FARE_CLASSES, weights=FARE_CLASS_WEIGHTS, k=1)[0]
    pct_discount_fares = round(clamp(random.gauss(0.35 - engagement * 0.15, 0.15), 0.0, 1.0), 3)

    # --- Route diversity ----------------------------------------------------
    unique_routes_lifetime = max(1, int(clamp(random.gauss(2 + engagement * 6, 2), 1, 25)))
    route_diversity_score = round(clamp(unique_routes_lifetime / max(total_bookings_lifetime, 1), 0.0, 1.0), 3)
    primary_hub = random.choice(HUBS)

    # --- Seasonality ---------------------------------------------------------
    pct_bookings_summer = round(clamp(random.gauss(0.35, 0.12), 0.0, 1.0), 3)
    pct_bookings_holiday = round(clamp(random.gauss(0.15, 0.08), 0.0, 1.0), 3)

    # --- Points earning / redemption ----------------------------------------
    points_balance = max(0, int(random.gauss(4000 + engagement * 15000, 6000)))
    points_earned_last_90d = max(0, int(random.gauss(engagement * 3500, 1500)))
    points_earning_velocity = round(points_earned_last_90d / 90, 2)
    redemption_gap_days = int(clamp(random.expovariate(1 / (30 + (1 - engagement) * 400)), 1, 1000))
    points_redeemed_last_365d = max(0, int(random.gauss(engagement * 12000, 6000)))
    points_expiring_soon = 1 if (points_balance > 0 and redemption_gap_days > 400 and random.random() < 0.5) else 0

    # --- Customer support -----------------------------------------------------
    complaints_last_365d = max(0, int(random.gauss((1 - engagement) * 2.2, 1.0)))
    support_tickets_open = 1 if (complaints_last_365d > 0 and random.random() < 0.2) else 0
    avg_support_csat = round(clamp(random.gauss(4.2 - (1 - engagement) * 1.5, 0.7), 1.0, 5.0), 2) if complaints_last_365d > 0 else round(clamp(random.gauss(4.5, 0.4), 1.0, 5.0), 2)

    # --- Promotion response ---------------------------------------------------
    promos_sent_last_180d = max(0, int(random.gauss(6, 2)))
    promo_response_rate = round(clamp(random.gauss(engagement * 0.6, 0.2), 0.0, 1.0), 3)
    promos_redeemed_last_180d = int(round(promos_sent_last_180d * promo_response_rate))

    # --- Digital engagement ------------------------------------------------
    app_logins_last_90d = max(0, int(random.gauss(engagement * 20, 8)))
    email_open_rate = round(clamp(random.gauss(engagement * 0.55 + 0.05, 0.15), 0.0, 1.0), 3)

    # --- RFM composite (0-100, higher = healthier) --------------------------
    recency_score = round(clamp(100 - (days_since_last_booking / 9), 0, 100), 1)
    frequency_score = round(clamp(bookings_last_365d * 12, 0, 100), 1)
    monetary_score = round(clamp(total_spend_lifetime / 100, 0, 100), 1)
    rfm_score = round((recency_score + frequency_score + monetary_score) / 3, 1)

    # --- Churn label ----------------------------------------------------------
    # Weighted risk score blending inactivity, redemption gap, low engagement,
    # and complaints — then thresholded with noise so the label is realistic
    # (correlated with features) rather than trivially separable.
    risk_score = (
        0.35 * clamp(days_since_last_booking / 365, 0, 1)
        + 0.20 * clamp(redemption_gap_days / 500, 0, 1)
        + 0.20 * (1 - engagement)
        + 0.15 * clamp(complaints_last_365d / 3, 0, 1)
        + 0.10 * (1 - promo_response_rate)
    )
    risk_score = clamp(risk_score + random.gauss(0, 0.08), 0, 1)
    churn_label = 1 if risk_score > 0.45 else 0

    return {
        "member_id": f"TB{member_id:06d}",
        "tier": tier,
        "enrollment_date": enrollment_dt.isoformat(),
        "tenure_days": tenure_days,
        "primary_hub": primary_hub,
        "days_since_last_booking": days_since_last_booking,
        "bookings_last_90d": bookings_last_90d,
        "bookings_last_180d": bookings_last_180d,
        "bookings_last_365d": bookings_last_365d,
        "total_bookings_lifetime": total_bookings_lifetime,
        "avg_fare": avg_fare,
        "total_spend_lifetime": total_spend_lifetime,
        "fare_class_most_common": fare_class,
        "pct_discount_fares": pct_discount_fares,
        "unique_routes_lifetime": unique_routes_lifetime,
        "route_diversity_score": route_diversity_score,
        "pct_bookings_summer": pct_bookings_summer,
        "pct_bookings_holiday": pct_bookings_holiday,
        "points_balance": points_balance,
        "points_earned_last_90d": points_earned_last_90d,
        "points_earning_velocity": points_earning_velocity,
        "redemption_gap_days": redemption_gap_days,
        "points_redeemed_last_365d": points_redeemed_last_365d,
        "points_expiring_soon": points_expiring_soon,
        "complaints_last_365d": complaints_last_365d,
        "support_tickets_open": support_tickets_open,
        "avg_support_csat": avg_support_csat,
        "promos_sent_last_180d": promos_sent_last_180d,
        "promos_redeemed_last_180d": promos_redeemed_last_180d,
        "promo_response_rate": promo_response_rate,
        "app_logins_last_90d": app_logins_last_90d,
        "email_open_rate": email_open_rate,
        "recency_score": recency_score,
        "frequency_score": frequency_score,
        "monetary_score": monetary_score,
        "rfm_score": rfm_score,
        "churn_label": churn_label,
    }


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = [generate_member(i) for i in range(1, N_MEMBERS + 1)]

    with OUTPUT_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    churn_rate = sum(r["churn_label"] for r in rows) / len(rows)
    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH}")
    print(f"Churn rate: {churn_rate:.1%}")


if __name__ == "__main__":
    main()
