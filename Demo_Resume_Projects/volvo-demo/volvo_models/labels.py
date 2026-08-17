"""Single source of truth for the 8 classification categories from
Volvo_Architecture_Deep_Dive.md §2.4. Imported everywhere else that needs
category names/order: Postgres CHECK constraints (db/init/01_schema.sql
mirrors this list manually, since SQL can't import Python), OpenSearch's
`categories` field, the classifier's output head (Phase 4), and the UI's
display order (Phase 9).
"""
CATEGORIES: tuple[str, ...] = (
    "powertrain",
    "infotainment",
    "electrical",
    "braking",
    "software_update",
    "safety_concern",
    "parts_delay",
    "dealer_escalation",
)
