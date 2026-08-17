"""Bulk-seeds most of the synthetic corpus (Phase 2) as "historical" cases
through the same Phase 6 FastAPI endpoints -- no bypass of classification/
NER/escalation-check logic, mirroring NRG's explicit decision that its own
bulk-ingest CLI does not skip versioning/publish. Embeddings are batched
(embed_batch, one model call for the whole corpus) since that's the one
step cheap to batch without touching FastAPI's per-case /index-case
contract; classify/extract-entities/similar-cases/index-case are still
called once per case through the real endpoints.

The last RESERVED_COUNT cases (by file order) are deliberately NOT seeded,
so a demo session has genuinely new narratives available to submit live
through the Submit New Case tab (Phase 9) rather than only ever
re-submitting something already indexed. These are exactly the cases
Phase 2 authored last: the near-duplicate pairs used for Phase 5's
similarity verification, which also make good live-demo material since
seeding one half of a pair and live-submitting the other shows off
similarity search finding a real historical match.

Usage: python scripts/seed_historical_cases.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

from volvo_models.similarity import embed_batch  # noqa: E402

CASES_PATH = ROOT / "data" / "synthetic_cases" / "cases.jsonl"
RESERVED_COUNT = 10
FASTAPI_BASE_URL = "http://localhost:8100"


def main() -> None:
    with open(CASES_PATH) as f:
        all_cases = [json.loads(line) for line in f]

    seed_cases = all_cases[:-RESERVED_COUNT]
    reserved_cases = all_cases[-RESERVED_COUNT:]

    print(f"Total cases: {len(all_cases)}")
    print(f"Seeding: {len(seed_cases)}")
    print(f"Reserved for live demo (not seeded): {len(reserved_cases)}")
    print("Reserved case_ids:", [c["case_id"] for c in reserved_cases])

    print("\nBatch-embedding all seed narratives...")
    vectors = embed_batch([c["narrative_text"] for c in seed_cases])

    client = httpx.Client(base_url=FASTAPI_BASE_URL, timeout=30.0)
    escalated_count = 0
    failed_cases = []

    for i, (case, vector) in enumerate(zip(seed_cases, vectors)):
        classify_resp = client.post("/classify", json={"text": case["narrative_text"]})
        classify_resp.raise_for_status()
        classifications = classify_resp.json()["classifications"]

        entities_resp = client.post("/extract-entities", json={"text": case["narrative_text"]})
        entities_resp.raise_for_status()
        entities = entities_resp.json()["entities"]

        similar_resp = client.post("/similar-cases", json={"text": case["narrative_text"], "k": 5})
        similar_resp.raise_for_status()
        similar_cases = similar_resp.json()["similar_cases"]

        index_resp = client.post(
            "/index-case",
            json={
                "case_id": case["case_id"],
                "vin": case["vin"],
                "narrative_text": case["narrative_text"],
                "submitted_by": "bulk_seed",
                "dealer_location": case.get("dealer_location"),
                "mileage": case.get("mileage"),
                "vehicle_model": case.get("vehicle_model"),
                "model_year": case.get("model_year"),
                "classifications": classifications,
                "entities": entities,
                "narrative_vector": vector,
                "similar_cases": similar_cases,
            },
        )
        if index_resp.status_code != 200:
            failed_cases.append((case["case_id"], index_resp.status_code, index_resp.text))
            continue

        result = index_resp.json()
        if result["escalation_raised"]:
            escalated_count += 1

        if (i + 1) % 20 == 0 or (i + 1) == len(seed_cases):
            print(f"  Seeded {i + 1}/{len(seed_cases)}...")

    client.close()

    print(f"\nDone. Seeded {len(seed_cases) - len(failed_cases)}/{len(seed_cases)} cases.")
    print(f"Escalations raised during seeding: {escalated_count}")
    if failed_cases:
        print(f"FAILED: {len(failed_cases)} cases:")
        for case_id, status, text in failed_cases:
            print(f"  {case_id}: HTTP {status} - {text[:200]}")

    reserved_path = ROOT / "data" / "synthetic_cases" / "reserved_for_live_demo.jsonl"
    with open(reserved_path, "w") as f:
        for case in reserved_cases:
            f.write(json.dumps(case) + "\n")
    print(f"\nReserved cases written to {reserved_path} for reference during live demos.")


if __name__ == "__main__":
    main()
