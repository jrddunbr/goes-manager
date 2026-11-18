"""S3 storage and identity helpers."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import tempfile

logger = logging.getLogger(__name__)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_source_object_key(source_root: Path, path: Path) -> str:
    relative = path.relative_to(source_root)
    return str(relative).replace("\\", "/")


class RustFSClient:
    def __init__(self, endpoint: str, access_key: str, secret_key: str) -> None:
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key

    def _client(self):
        import boto3
        from botocore.config import Config

        if hasattr(self, "_cached_client"):
            return self._cached_client
        self._cached_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 5},
                          connect_timeout=10, read_timeout=120),
        )
        return self._cached_client

    def ensure_bucket(self, bucket: str) -> None:
        from botocore.exceptions import ClientError

        client = self._client()
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            status_code = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if error_code not in {"404", "NoSuchBucket", "NotFound"} and status_code not in {404}:
                raise
            logger.info("Creating bucket %s on %s", bucket, self.endpoint)
            client.create_bucket(Bucket=bucket)

    def put_object(self, bucket: str, key: str, path: Path, checksum: str | None = None) -> dict[str, object]:
        self.ensure_bucket(bucket)
        client = self._client()
        from boto3.s3.transfer import TransferConfig

        checksum = checksum or sha256_file(path)
        client.upload_file(str(path), bucket, key,
                           ExtraArgs={"Metadata": {"sha256": checksum}},
                           Config=TransferConfig(use_threads=False, multipart_chunksize=8 * 1024 * 1024))
        head = client.head_object(Bucket=bucket, Key=key)
        logger.info("Uploaded %s to %s/%s via %s", path, bucket, key, self.endpoint)
        return {
            "bucket": bucket,
            "key": key,
            "etag": str(head.get("ETag", "")).strip('"'),
            "size": head["ContentLength"],
            "sha256": checksum,
        }

    def get_object_bytes(self, bucket: str, key: str) -> bytes:
        client = self._client()
        response = client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def delete_object(self, bucket: str, key: str) -> None:
        client = self._client()
        client.delete_object(Bucket=bucket, Key=key)
        logger.info("Deleted object %s/%s via %s", bucket, key, self.endpoint)

    def object_exists(self, bucket: str, key: str) -> bool:
        from botocore.exceptions import ClientError

        client = self._client()
        try:
            client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            status_code = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if error_code in {"404", "NoSuchKey", "NotFound"} or status_code == 404:
                return False
            raise

    def download_to_temp_path(self, bucket: str, key: str, suffix: str = "") -> Path:
        payload = self.get_object_bytes(bucket, key)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(payload)
            return Path(handle.name)

    def verify_object(self, bucket: str, key: str, checksum: str, size: int) -> None:
        """Read back incrementally; ETags are not checksums for multipart uploads."""
        response = self._client().get_object(Bucket=bucket, Key=key)
        digest = hashlib.sha256()
        actual_size = 0
        body = response["Body"]
        try:
            for chunk in body.iter_chunks(chunk_size=1024 * 1024):
                digest.update(chunk)
                actual_size += len(chunk)
        finally:
            body.close()
        if actual_size != size or digest.hexdigest() != checksum:
            raise RuntimeError(f"Object verification failed: {bucket}/{key}")

    def iter_objects(self, bucket: str):
        paginator = self._client().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, PaginationConfig={"PageSize": 500}):
            yield from page.get("Contents", [])

    def head_object(self, bucket: str, key: str) -> dict:
        return self._client().head_object(Bucket=bucket, Key=key)
