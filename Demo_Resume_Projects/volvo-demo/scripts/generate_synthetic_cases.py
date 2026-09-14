"""Authors synthetic Volvo dealer warranty/complaint narratives and
heuristically labels them via label_heuristics.py, for use by PySpark
preprocessing (Phase 3), DistilBERT fine-tuning (Phase 4), and Sentence-BERT
similarity verification (Phase 5).

Narratives are genuine short warranty-complaint sentences (not gibberish),
covering all 8 categories from Volvo_Architecture_Deep_Dive.md with clean
single-label examples, a deliberate multi-label subset, a deliberate
safety_concern subset (needed later to prove the escalation pipeline fires
correctly), a handful of injected dealer abbreviations/boilerplate (so
Phase 3's PySpark cleaning step has real work to do), and 2-3 near-duplicate
pairs (for Phase 5's similarity verification).

Usage: python scripts/generate_synthetic_cases.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from label_heuristics import label_narrative  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent))
from volvo_models.labels import CATEGORIES  # noqa: E402

random.seed(42)

DEALER_LOCATIONS = [
    "Volvo of Mahwah, NJ", "Volvo Cars Manhattan, NY", "Volvo of Stamford, CT",
    "Volvo Cars Paramus, NJ", "Volvo of Bethesda, MD", "Volvo Cars Boston, MA",
    "Volvo of Chicago, IL", "Volvo Cars Denver, CO", "Volvo of Austin, TX",
    "Volvo Cars Seattle, WA",
]
VEHICLE_MODELS = ["XC90", "XC60", "XC40", "S60", "S90", "V60", "V90"]

BOILERPLATE_PREFIXES = [
    "customer states: ",
    "cust reports: ",
    "per customer: ",
    "",  # most narratives have no boilerplate at all
    "",
    "",
]

# Common dealer-shop abbreviations deliberately left un-expanded here so
# Phase 3's PySpark normalization step has real, verifiable work to do.
ABBREVIATED_PHRASES = {
    "check engine light": ["chk eng lt", "check engine light"],
    "as soon as possible": ["asap", "as soon as possible"],
    "check engine": ["chk eng", "check engine"],
}


def maybe_abbreviate(text: str) -> str:
    """Randomly substitutes a full phrase for its shop-abbreviated form,
    for a subset of narratives, so Phase 3's abbreviation-expansion UDF has
    genuine input to normalize.
    """
    for full, variants in ABBREVIATED_PHRASES.items():
        if full in text.lower() and random.random() < 0.4:
            abbrev = variants[0]
            idx = text.lower().find(full)
            text = text[:idx] + abbrev + text[idx + len(full):]
    return text


# --- Per-category narrative templates -------------------------------------
# Each entry is a template string; {model} is filled from VEHICLE_MODELS.
# These are deliberately single-category-clean (per label_heuristics.py)
# unless noted otherwise below in MULTI_LABEL_NARRATIVES /
# SAFETY_CONCERN_NARRATIVES.

POWERTRAIN_TEMPLATES = [
    "Vehicle {model} stalls at idle after driving for about ten minutes.",
    "Customer reports rough idle and hesitation on acceleration in the {model}.",
    "Engine misfire under load, especially on highway on-ramps, {model}.",
    "Transmission hesitates to shift into third gear on the {model}.",
    "Coolant level dropping steadily over two weeks with no visible leak, {model}.",
    "Turbocharger whine under acceleration, customer says it's gotten louder, {model}.",
    "{model} has an oil leak visible on the driveway after overnight parking.",
    "Customer reports the {model} is overheating on long highway drives.",
]

INFOTAINMENT_TEMPLATES = [
    "Infotainment touchscreen freezes randomly while driving the {model}.",
    "Navigation system loses GPS signal intermittently in the {model}.",
    "Apple CarPlay disconnects every few minutes on the {model}.",
    "Backup camera display goes black when shifting into reverse, {model}.",
    "Bluetooth pairing fails consistently with customer's phone, {model}.",
    "Sound system cuts out at random intervals while driving, {model}.",
    "Head unit reboots itself two or three times per drive in the {model}.",
]

ELECTRICAL_TEMPLATES = [
    "Customer reports the {model} battery is dead every morning despite driving daily.",
    "Multiple dashboard warning lights illuminate randomly on the {model}.",
    "Power windows on the {model} stopped responding on the driver's side.",
    "{model} won't start intermittently, seems to be an electrical fault.",
    "Interior lights flicker when the {model} is running.",
    "Customer noticed a burning smell near the fuse box on the {model} but no smoke.",
]

BRAKING_TEMPLATES = [
    "Brake pedal feels soft and sinks to the floor on the {model}.",
    "Grinding noise from the brakes when stopping at low speed, {model}.",
    "ABS warning light stays on continuously in the {model}.",
    "Squealing brakes on the {model}, worse in the morning.",
    "Customer reports the {model}'s brake fluid level has been low twice this month.",
]

SOFTWARE_UPDATE_TEMPLATES = [
    "Over-the-air software update failed twice on the {model}, stuck at 40 percent.",
    "Firmware update caused the {model}'s climate control to stop responding.",
    "Customer's {model} is asking for a system update that won't complete.",
    "Dealer recommended a reflash after the {model}'s cruise control stopped engaging.",
]

PARTS_DELAY_TEMPLATES = [
    "Replacement part for the {model} is backordered with no estimated arrival.",
    "Customer's {model} has been waiting on a part for three weeks.",
    "Dealer reports a supply delay on the sensor needed for the {model} repair.",
    "Part for the {model} is on order, no ETA provided by parts department.",
]

DEALER_ESCALATION_TEMPLATES = [
    "Customer has brought the {model} in three times for the same issue, still not fixed.",
    "Dealer could not diagnose the recurring problem on the {model} after two visits.",
    "Customer requesting escalation to management after unresolved {model} repair attempts.",
    "This is the customer's third visit for the same {model} concern this quarter.",
]

# Deliberate multi-label narratives -- these intentionally match keywords
# from 2+ categories at once, per label_heuristics.py, mirroring
# Volvo_Architecture_Deep_Dive.md §2.4's own example (infotainment failure
# that also causes unexpected battery drain).
MULTI_LABEL_NARRATIVES = [
    "Infotainment head unit reboots constantly and customer also reports the {model}'s battery drain overnight.",
    "Customer's {model} has a check engine light on along with intermittent electrical dashboard warning lights.",
    "Backup camera display is black and customer also noticed the {model} won't start intermittently.",
    "Brake pedal feels soft and the ABS warning light is on, customer also mentions a burning smell near the fuse box, {model}.",
    "Software update failed on the {model} and now the touchscreen infotainment display freezes constantly.",
    "Customer's {model} has been in three times for the same electrical issue -- dealer could not diagnose the dashboard warning lights.",
]

# Deliberate, unambiguous safety_concern narratives -- needed to prove the
# escalation pipeline fires correctly on both direct_classification and
# (via near-duplicate similarity in Phase 6) recurring_pattern triggers.
SAFETY_CONCERN_NARRATIVES = [
    "Customer reports sudden brake failure while driving the {model} on the highway.",
    "Airbag warning light stayed on and then the airbag deployed unexpectedly at low speed in the {model}.",
    "Customer smelled smoke and saw a small amount of visible smoke from under the hood of the {model}.",
    "Steering lock engaged unexpectedly while the {model} was in motion, customer had momentary loss of control.",
    "Unintended acceleration reported by customer while parking the {model}, brakes did not stop the vehicle immediately.",
    "Customer reports the {model} experienced sudden brake failure a second time this month.",
]

# Near-duplicate pairs for Phase 5's Sentence-BERT similarity verification --
# each pair describes the same underlying issue in different wording.
NEAR_DUPLICATE_PAIRS = [
    (
        "Customer reports sudden brake failure while driving the {model} on the highway.",
        "The {model}'s brakes suddenly stopped working while the customer was driving on the interstate.",
    ),
    (
        "Infotainment touchscreen freezes randomly while driving the {model}.",
        "The {model}'s infotainment screen keeps freezing up unpredictably during drives.",
    ),
    (
        "Engine misfire under load, especially on highway on-ramps, {model}.",
        "The {model} engine misfires when accelerating hard, most noticeable merging onto highways.",
    ),
]


def build_case(case_id: str, narrative: str, categories: list[str] | None = None) -> dict:
    model = random.choice(VEHICLE_MODELS)
    narrative = narrative.format(model=model)
    narrative = maybe_abbreviate(narrative)
    prefix = random.choice(BOILERPLATE_PREFIXES)
    full_text = prefix + narrative

    resolved_categories = categories if categories is not None else label_narrative(full_text)

    # 17-char synthetic VIN, clearly fake and distinctly prefixed ("YV1VOLVO"
    # is not a real WMI+VDS combination). Digits-only suffix derived from the
    # case_id's numeric portion (case_id itself contains a hyphen, e.g.
    # "CASE-0001", which is not a valid VIN character -- extracting only the
    # digits avoids embedding that hyphen into the VIN, a bug caught during
    # Phase 3 verification when every generated VIN turned out non-alphanumeric).
    case_number = "".join(ch for ch in case_id if ch.isdigit())
    vin = ("YV1VOLVO" + case_number.zfill(9))[:17]

    return {
        "case_id": case_id,
        "vin": vin,
        "narrative_text": full_text,
        "categories": resolved_categories,
        "dealer_location": random.choice(DEALER_LOCATIONS),
        "mileage": random.randint(1000, 60000),
        "vehicle_model": model,
        "model_year": random.randint(2021, 2025),
    }


def generate_all_cases() -> list[dict]:
    cases: list[dict] = []
    counter = 1

    def add(narrative_pool: list[str], count: int, categories: list[str] | None = None) -> None:
        nonlocal counter
        for _ in range(count):
            template = random.choice(narrative_pool)
            case_id = f"CASE-{counter:04d}"
            cases.append(build_case(case_id, template, categories))
            counter += 1

    # Clean single-label examples per category (~12 each = 96 total)
    add(POWERTRAIN_TEMPLATES, 12)
    add(INFOTAINMENT_TEMPLATES, 12)
    add(ELECTRICAL_TEMPLATES, 12)
    add(BRAKING_TEMPLATES, 12)
    add(SOFTWARE_UPDATE_TEMPLATES, 12)
    add(PARTS_DELAY_TEMPLATES, 12)
    add(DEALER_ESCALATION_TEMPLATES, 12)

    # Multi-label subset (~15-20% of total -- 18 of ~114 non-safety cases so far)
    add(MULTI_LABEL_NARRATIVES, 18)

    # Deliberate safety_concern subset
    add(SAFETY_CONCERN_NARRATIVES, 12)

    # Near-duplicate pairs (as their own distinct cases, using the exact
    # wording from NEAR_DUPLICATE_PAIRS rather than the template pools
    # above, so Phase 5 can look them up specifically by case_id)
    for a_text, b_text in NEAR_DUPLICATE_PAIRS:
        model = random.choice(VEHICLE_MODELS)
        for text in (a_text, b_text):
            case_id = f"CASE-{counter:04d}"
            cases.append(build_case(case_id, text.replace("{model}", "{model}")))
            counter += 1

    return cases


def stratified_split(cases: list[dict], val_fraction: float = 0.15) -> tuple[list[dict], list[dict]]:
    """Best-effort stratified split: for each category, ~val_fraction of
    the cases carrying that category go to val. Since cases can carry
    multiple categories, this is necessarily approximate (a stratified
    split is well-defined only for single-label data) -- cases are
    shuffled once and then assigned round-robin per category bucket,
    which is a reasonable multi-label approximation for a demo-sized
    dataset.
    """
    shuffled = cases[:]
    random.shuffle(shuffled)

    val_ids: set[str] = set()
    category_seen: dict[str, int] = {c: 0 for c in CATEGORIES}

    for case in shuffled:
        for category in case["categories"]:
            category_seen[category] += 1

    category_val_target = {c: max(1, round(n * val_fraction)) for c, n in category_seen.items()}
    category_val_count: dict[str, int] = {c: 0 for c in CATEGORIES}

    for case in shuffled:
        if case["case_id"] in val_ids:
            continue
        eligible = any(
            category_val_count[c] < category_val_target[c] for c in case["categories"]
        ) if case["categories"] else False
        if eligible:
            val_ids.add(case["case_id"])
            for c in case["categories"]:
                category_val_count[c] += 1

    train = [c for c in cases if c["case_id"] not in val_ids]
    val = [c for c in cases if c["case_id"] in val_ids]
    return train, val


def main() -> None:
    cases = generate_all_cases()

    out_dir = Path(__file__).parent.parent / "data" / "synthetic_cases"
    out_dir.mkdir(parents=True, exist_ok=True)
    cases_path = out_dir / "cases.jsonl"
    with open(cases_path, "w") as f:
        for case in cases:
            f.write(json.dumps(case) + "\n")

    train, val = stratified_split(cases)
    training_dir = Path(__file__).parent.parent / "data" / "training"
    training_dir.mkdir(parents=True, exist_ok=True)
    with open(training_dir / "train.jsonl", "w") as f:
        for case in train:
            f.write(json.dumps(case) + "\n")
    with open(training_dir / "val.jsonl", "w") as f:
        for case in val:
            f.write(json.dumps(case) + "\n")

    # --- Verification output ---
    print(f"Total cases generated: {len(cases)}")
    print(f"Written to: {cases_path}")
    print(f"Train: {len(train)}, Val: {len(val)}")

    print("\nPer-category counts:")
    category_counts = {c: 0 for c in CATEGORIES}
    for case in cases:
        for c in case["categories"]:
            category_counts[c] += 1
    for c, count in category_counts.items():
        print(f"  {c}: {count}")

    multi_label_cases = [c for c in cases if len(c["categories"]) > 1]
    print(f"\nMulti-label cases: {len(multi_label_cases)} ({100 * len(multi_label_cases) / len(cases):.1f}%)")
    print("Sample multi-label cases:")
    for case in multi_label_cases[:5]:
        print(f"  [{case['case_id']}] categories={case['categories']}")
        print(f"    narrative: {case['narrative_text']}")

    unlabeled = [c for c in cases if not c["categories"]]
    if unlabeled:
        print(f"\nWARNING: {len(unlabeled)} cases matched zero categories:")
        for case in unlabeled:
            print(f"  [{case['case_id']}] {case['narrative_text']}")

    vin_lengths = {len(c["vin"]) for c in cases}
    print(f"\nVIN lengths present: {vin_lengths} (expect {{17}})")

    train_ids = {c["case_id"] for c in train}
    val_ids = {c["case_id"] for c in val}
    overlap = train_ids & val_ids
    print(f"Train/val case_id overlap: {len(overlap)} (expect 0)")


if __name__ == "__main__":
    main()
