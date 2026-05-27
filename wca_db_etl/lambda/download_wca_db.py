import os
import io
import zipfile
import tempfile
from typing import Dict

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

EXPORT_URL = "https://www.worldcubeassociation.org/export/results/v2/tsv"
BUCKET_NAME = "wcastats-wca-results-db-268977875744-ap-southeast-2-an"

# Files that should be partitioned
# TODO could be good to partition by year as well, and partition results attempts file too
# Both would require joining to get this data
PARTITIONED_TABLES = {
    "WCA_export_Results.tsv": ["eventId"],
}

# dtype hints to reduce memory usage
DTYPE_HINTS: Dict[str, Dict[str, str]] = {
    "WCA_export_Results.tsv": {
        "competitionId": "string",
        "eventId": "string",
        "roundTypeId": "string",
        "personId": "string",
        "personName": "string",
        "countryId": "string",
        "formatId": "string",
    },
}

s3_client = boto3.client("s3")

def lambda_handler(event, context):
    print("Downloading WCA export...")

    response = requests.get(EXPORT_URL, stream=True, timeout=300)
    response.raise_for_status()

    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, "wca_export.zip")

        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

        print(f"Saved ZIP to {zip_path}")

        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        print(f"Extracted files to {extract_dir}")

        process_directory(extract_dir)

    return {
        "statusCode": 200,
        "body": "WCA export processed successfully"
    }

def process_directory(directory: str):
    for filename in os.listdir(directory):
        if not filename.endswith(".tsv"):
            continue

        file_path = os.path.join(directory, filename)

        print(f"Processing {filename}...")

        if filename in PARTITIONED_TABLES:
            process_partitioned_tsv(file_path, filename)
        else:
            process_standard_tsv(file_path, filename)

# TODO combine these into one function?

# def process_tsv(file_path: str, filename: str, is_partitioned: bool):
#     table_name = filename.replace("WCA_export_", "").replace(".tsv", "").lower()

#     if is_partitioned:
#         partition_columns = PARTITIONED_TABLES[filename]

#     dtype_map = DTYPE_HINTS.get(filename)

def process_standard_tsv(file_path: str, filename: str):
    table_name = filename.replace("WCA_export_", "").replace(".tsv", "").lower()

    dtype_map = DTYPE_HINTS.get(filename)

    df = pd.read_csv(
        file_path,
        sep="\t",
        dtype=dtype_map,
        low_memory=False,
    )

    parquet_buffer = io.BytesIO()

    table = pa.Table.from_pandas(df)
    pq.write_table(table, parquet_buffer, compression="snappy")

    parquet_buffer.seek(0)

    s3_key = f"raw/{table_name}/{table_name}.parquet"

    print(f"Uploading {s3_key}...")

    s3_client.upload_fileobj(
        parquet_buffer,
        BUCKET_NAME,
        s3_key,
    )

def process_partitioned_tsv(file_path: str, filename: str):
    table_name = filename.replace("WCA_export_", "").replace(".tsv", "").lower()

    partition_columns = PARTITIONED_TABLES[filename]

    dtype_map = DTYPE_HINTS.get(filename)

    chunksize = 250_000

    chunk_number = 0

    for chunk in pd.read_csv(
        file_path,
        sep="\t",
        dtype=dtype_map,
        low_memory=False,
        chunksize=chunksize,
    ):
        chunk_number += 1

        print(f"Processing chunk {chunk_number}...")

        grouped = chunk.groupby(partition_columns)

        for partition_values, partition_df in grouped:
            if not isinstance(partition_values, tuple):
                partition_values = (partition_values,)

            partition_path = "/".join(
                f"{column}={value}"
                for column, value in zip(partition_columns, partition_values)
            )

            parquet_buffer = io.BytesIO()

            table = pa.Table.from_pandas(partition_df, preserve_index=False)
            pq.write_table(table, parquet_buffer, compression="snappy")

            parquet_buffer.seek(0)

            s3_key = (
                f"raw/{table_name}/"
                f"{partition_path}/"
                f"part-{chunk_number}.parquet"
            )

            s3_client.upload_fileobj(
                parquet_buffer,
                BUCKET_NAME,
                s3_key,
            )

    print(f"Finished partitioned upload for {table_name}")