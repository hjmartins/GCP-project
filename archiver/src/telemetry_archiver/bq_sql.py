"""Executa os SQLs de archiver/sql/ (escritos à parte, sem Python).

Identificadores (projeto, dataset, tabela, conexão, caminho do metadata) entram por
str.format, porque o BigQuery não aceita parâmetro de consulta em nome de tabela. Valores
(datas) entram como parâmetros de consulta (@cutoff).
"""

import os
from datetime import date
from pathlib import Path

from google.cloud import bigquery

# No repositório: archiver/sql/. Na imagem Docker: ARCHIVER_SQL_DIR=/app/sql.
SQL_DIR = Path(os.environ.get("ARCHIVER_SQL_DIR", Path(__file__).resolve().parents[2] / "sql"))


def render(name: str, sql_dir: Path = SQL_DIR, **identifiers: str) -> str:
    return (sql_dir / name).read_text().format(**identifiers)


def run(client: bigquery.Client, sql: str, *, cutoff: date | None = None) -> bigquery.QueryJob:
    params = [bigquery.ScalarQueryParameter("cutoff", "DATE", cutoff)] if cutoff else []
    job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
    job.result()
    return job
