"""Verifies the OpenSearch index exists with the expected knn_vector
schema, and reports cluster health + current document count -- run after
`docker compose up -d` and after any bulk-seed/ingestion run.

Usage: python scripts/check_opensearch_health.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from volvo_retrieval.opensearch_client import INDEX_NAME, VECTOR_DIM, ensure_index


def main() -> None:
    client = ensure_index()

    health = client.cluster.health()
    print(f"Cluster status: {health['status']}")
    print(f"Number of nodes: {health['number_of_nodes']}")

    exists = client.indices.exists(index=INDEX_NAME)
    print(f"Index '{INDEX_NAME}' exists: {exists}")
    if not exists:
        print("\nIndex missing after ensure_index() -- unexpected.")
        sys.exit(1)

    mapping = client.indices.get_mapping(index=INDEX_NAME)
    properties = mapping[INDEX_NAME]["mappings"]["properties"]

    vector_field = properties.get("narrative_vector", {})
    vector_ok = (
        vector_field.get("type") == "knn_vector"
        and vector_field.get("dimension") == VECTOR_DIM
    )
    print(f"narrative_vector (knn_vector, dim={VECTOR_DIM}): {'OK' if vector_ok else 'MISSING/WRONG'}")

    count_resp = client.count(index=INDEX_NAME)
    print(f"Document count: {count_resp['count']}")

    if health["status"] not in ("green", "yellow"):
        print("\nCluster status is not green/yellow.")
        sys.exit(1)
    if not vector_ok:
        print("\nSchema mismatch -- index may need to be deleted and recreated.")
        sys.exit(1)

    print("\nOpenSearch index schema OK.")


if __name__ == "__main__":
    main()
