"""Escrita dos Parquet no layout Bronze: <entidade>/dt=YYYY-MM-DD/part-000.parquet.

O nome do arquivo é fixo: rodar o mesmo dia de novo sobrescreve em vez de duplicar.
OUTPUT_URI aceita pasta local (./data) ou bucket (gs://bucket).
"""

from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.fs as pafs
import pyarrow.parquet as pq


def partition_path(entity: str, day: date) -> str:
    return f"{entity}/dt={day.isoformat()}/part-000.parquet"


def write_table(table: pa.Table, output_uri: str, entity: str, day: date) -> str:
    if "://" in output_uri:
        fs, root = pafs.FileSystem.from_uri(output_uri)
    else:
        fs, root = pafs.LocalFileSystem(), str(Path(output_uri).resolve())

    path = f"{root.rstrip('/')}/{partition_path(entity, day)}"
    if isinstance(fs, pafs.LocalFileSystem):
        fs.create_dir(path.rsplit("/", 1)[0], recursive=True)
    pq.write_table(table, path, filesystem=fs, compression="zstd")
    return path
