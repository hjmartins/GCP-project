"""O catálogo Iceberg é um arquivo SQLite guardado no bucket frio.

Simples e grátis para um escritor só, uma vez por dia. O upload usa if_generation_match: se
outro processo tiver alterado o catálogo desde o download, o upload falha em vez de
sobrescrever (proteção contra dois archivers ao mesmo tempo).
"""

from pathlib import Path

from google.api_core.exceptions import NotFound
from google.cloud import storage


def download(client: storage.Client, bucket: str, obj: str, local_path: Path) -> int:
    """Baixa o catálogo e devolve a generation do objeto (0 = ainda não existe)."""
    blob = client.bucket(bucket).blob(obj)
    try:
        blob.reload()
    except NotFound:
        return 0
    blob.download_to_filename(str(local_path))
    return blob.generation


def upload(
    client: storage.Client, bucket: str, obj: str, local_path: Path, generation: int
) -> None:
    blob = client.bucket(bucket).blob(obj)
    blob.upload_from_filename(str(local_path), if_generation_match=generation)
