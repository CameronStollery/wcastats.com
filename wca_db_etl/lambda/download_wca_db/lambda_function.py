import io
import os
import tempfile
import zipfile

import boto3
import polars as pl
import requests


EXPORT_URL = "https://www.worldcubeassociation.org/export/results/v2/tsv"

BUCKET_NAME = (
    "wcastats-wca-results-db-268977875744-ap-southeast-2-an"
)

RESULTS_FILE = "WCA_export_results.tsv"

s3_client = boto3.client("s3")


def lambda_handler(event, context):
    print("Starting WCA export ingestion...")

    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = download_export(temp_dir)
        extract_dir = extract_export(zip_path, temp_dir)

        process_directory(extract_dir)

    print("Finished WCA export ingestion")

    return {
        "statusCode": 200,
        "body": "WCA export processed successfully",
    }


def download_export(temp_dir: str) -> str:
    print("Downloading WCA export...")

    response = requests.get(
        EXPORT_URL,
        stream=True,
        timeout=300,
    )

    response.raise_for_status()

    zip_path = os.path.join(temp_dir, "wca_export.zip")

    with open(zip_path, "wb") as f:
        for chunk in response.iter_content(
            chunk_size=1024 * 1024
        ):
            if chunk:
                f.write(chunk)

    print(f"Downloaded export to {zip_path}")

    return zip_path


def extract_export(zip_path: str, temp_dir: str) -> str:
    extract_dir = os.path.join(temp_dir, "extracted")

    os.makedirs(extract_dir, exist_ok=True)

    print("Extracting ZIP...")

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_dir)

    print(f"Extracted files to {extract_dir}")

    return extract_dir


def process_directory(directory: str):
    for filename in os.listdir(directory):
        if not filename.endswith(".tsv"):
            continue

        file_path = os.path.join(directory, filename)

        print(f"Processing {filename}...")

        if filename == RESULTS_FILE:
            process_results_table(file_path)
        else:
            process_standard_table(file_path, filename)


def create_lazyframe(file_path: str) -> pl.LazyFrame:
    """
    Create a Polars LazyFrame with settings tuned for
    WCA TSV export quirks and malformed quoting.
    """

    return pl.scan_csv(
        file_path,
        separator="\t",
        quote_char=None,
        infer_schema_length=10000,
        ignore_errors=True,
        truncate_ragged_lines=True,
        low_memory=True,
    )


def process_standard_table(
    file_path: str,
    filename: str,
):
    table_name = (
        filename
        .replace("WCA_export_", "")
        .replace(".tsv", "")
        .lower()
    )

    print(f"Streaming {filename}...")

    lazy_df = create_lazyframe(file_path)

    parquet_buffer = io.BytesIO()

    (
        lazy_df
        .collect(streaming=True)
        .write_parquet(
            parquet_buffer,
            compression="snappy",
        )
    )

    parquet_buffer.seek(0)

    s3_key = (
        f"raw/{table_name}/"
        f"{table_name}.parquet"
    )

    print(f"Uploading {s3_key}...")

    s3_client.upload_fileobj(
        parquet_buffer,
        BUCKET_NAME,
        s3_key,
    )

    print(f"Uploaded {s3_key}")


def process_results_table(file_path: str):
    """
    Process WCA results table partitioned by event_id.
    """

    table_name = "results"

    print("Creating lazy scan for results table...")

    lazy_df = create_lazyframe(file_path)

    print("Collecting distinct event IDs...")

    event_ids = (
        lazy_df
        .select("event_id")
        .unique()
        .collect(streaming=True)
        .to_series()
        .drop_nulls()
        .to_list()
    )

    print(f"Found {len(event_ids)} event partitions")

    for event_id in event_ids:
        print(f"Processing event_id={event_id}")

        parquet_buffer = io.BytesIO()

        (
            lazy_df
            .filter(
                pl.col("event_id") == event_id
            )
            .drop("event_id")       # Athena derives column from path as files are partitioned by event_id
            .collect(streaming=True)
            .write_parquet(
                parquet_buffer,
                compression="snappy",
            )
        )

        parquet_buffer.seek(0)

        s3_key = (
            f"raw/{table_name}/"
            f"event_id={event_id}/"
            f"data.parquet"
        )

        s3_client.upload_fileobj(
            parquet_buffer,
            BUCKET_NAME,
            s3_key,
        )

    print("Finished processing results table")