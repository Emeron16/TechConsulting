"""Verifies the Qdrant collection exists with the expected dense+sparse
named-vector schema, and reports current point count -- run after
`docker compose up -d` and after any ingestion run.

Usage: python scripts/check_qdrant_health.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from nrg_retrieval.qdrant_client import (
    COLLECTION_NAME,
    DENSE_VECTOR_NAME,
    DENSE_VECTOR_SIZE,
    SPARSE_VECTOR_NAME,
    ensure_collection,
)


def main() -> None:
    client = ensure_collection()
    info = client.get_collection(COLLECTION_NAME)

    print(f"Collection: {COLLECTION_NAME}")
    print(f"Status: {info.status}")
    print(f"Points count: {info.points_count}")

    vectors_config = info.config.params.vectors
    sparse_config = info.config.params.sparse_vectors

    dense_ok = (
        isinstance(vectors_config, dict)
        and DENSE_VECTOR_NAME in vectors_config
        and vectors_config[DENSE_VECTOR_NAME].size == DENSE_VECTOR_SIZE
    )
    sparse_ok = isinstance(sparse_config, dict) and SPARSE_VECTOR_NAME in sparse_config

    print(f"Dense vector '{DENSE_VECTOR_NAME}' (size={DENSE_VECTOR_SIZE}): {'OK' if dense_ok else 'MISSING/WRONG'}")
    print(f"Sparse vector '{SPARSE_VECTOR_NAME}': {'OK' if sparse_ok else 'MISSING'}")

    if not (dense_ok and sparse_ok):
        print("\nSchema mismatch -- collection may need to be dropped and recreated.")
        sys.exit(1)

    print("\nQdrant collection schema OK.")


if __name__ == "__main__":
    main()
