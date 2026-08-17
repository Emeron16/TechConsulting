"""Real local-mode PySpark job that cleans/normalizes the synthetic
warranty narratives -- Volvo_Architecture_Deep_Dive.md §2.6's PySpark
preprocessing responsibility (boilerplate removal, abbreviation
normalization, structuring raw dealer text), run genuinely via
SparkSession.builder.master("local[*]"), not stubbed.

Requires JAVA_HOME and PYSPARK_PYTHON/PYSPARK_DRIVER_PYTHON to be set
correctly -- see volvo-demo/.env.example, and Phase 0's verification notes
in Volvo_Implementation_Plan.md for why PYSPARK_PYTHON must be pinned to
this venv's interpreter specifically (otherwise Spark's worker subprocess
can pick up a different Python minor version on PATH and crash every task
with PYTHON_VERSION_MISMATCH).

Usage: python scripts/preprocess_pyspark.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

# Must be set before importing pyspark so the JVM launch picks them up.
os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

from pyspark.sql import SparkSession  # noqa: E402
from pyspark.sql.functions import udf  # noqa: E402
from pyspark.sql.types import StringType  # noqa: E402

from volvo_models.text_normalize import normalize_text  # noqa: E402

INPUT_PATH = ROOT / "data" / "synthetic_cases" / "cases.jsonl"
OUTPUT_PATH = ROOT / "data" / "training" / "cases_cleaned.parquet"


def main() -> None:
    spark = (
        SparkSession.builder.master("local[*]")
        .appName("volvo-preprocess")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    # Even in local[*] mode, Spark's UDF executor runs in a separate Python
    # worker subprocess that does NOT inherit this script's sys.path
    # (confirmed the hard way: a first run failed at the actual .parquet()
    # write step -- not at .count(), since counting doesn't invoke the UDF
    # -- with ModuleNotFoundError: No module named 'volvo_models').
    # addPyFile requires a .py file or a .zip/.egg archive, not a bare
    # package directory, so the package is zipped to a temp file first.
    zip_path = Path(tempfile.gettempdir()) / "volvo_models.zip"
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=str(ROOT), base_dir="volvo_models")
    spark.sparkContext.addPyFile(str(zip_path))

    df = spark.read.json(str(INPUT_PATH))
    input_count = df.count()
    print(f"Read {input_count} rows from {INPUT_PATH}")

    normalize_udf = udf(normalize_text, StringType())
    cleaned_df = df.withColumn("narrative_text_cleaned", normalize_udf(df["narrative_text"]))

    output_count = cleaned_df.count()
    print(f"Row count after cleaning: {output_count}")
    if output_count != input_count:
        print("WARNING: row count changed during preprocessing -- rows were dropped.")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    cleaned_df.write.mode("overwrite").parquet(str(OUTPUT_PATH))
    print(f"Wrote cleaned output to {OUTPUT_PATH}")

    # --- Verification output: spot-check before/after for a few rows ---
    print("\nSpot-check (5 rows, before -> after):")
    sample = cleaned_df.select("case_id", "narrative_text", "narrative_text_cleaned").limit(5).collect()
    for row in sample:
        print(f"  [{row['case_id']}]")
        print(f"    before: {row['narrative_text']}")
        print(f"    after:  {row['narrative_text_cleaned']}")

    spark.stop()


if __name__ == "__main__":
    main()
