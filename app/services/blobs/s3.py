from pathlib import Path

from app.services.blobs import BlobError, validate_key


class S3BlobStore:
    """Thin wrapper over boto3. Credentials come from the ambient AWS chain (task role); never from settings."""

    def __init__(self, bucket: str, *, region: str | None = None, client=None):
        self.bucket = bucket
        self._client_obj = client
        self._region = region

    @property
    def _client(self):
        if self._client_obj is None:
            import boto3
            from botocore.config import Config
            self._client_obj = boto3.client(
                "s3", region_name=self._region,
                config=Config(retries={"max_attempts": 5, "mode": "standard"},
                              connect_timeout=5, read_timeout=60),
            )
        return self._client_obj

    def put_file(self, key: str, path: str | Path) -> None:
        key = validate_key(key)
        self._client.upload_file(str(path), self.bucket, key)

    def fetch_to_path(self, key: str, dest: str | Path) -> None:
        from botocore.exceptions import ClientError
        key = validate_key(key)
        try:
            self._client.download_file(self.bucket, key, str(dest))
        except ClientError as exc:
            if _is_missing(exc):
                raise BlobError("Object not found") from None
            raise

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        key = validate_key(key)
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if _is_missing(exc):
                return False
            raise

    def delete(self, key: str) -> None:
        key = validate_key(key)
        self._client.delete_object(Bucket=self.bucket, Key=key)


def _is_missing(exc) -> bool:
    return str(exc.response.get("Error", {}).get("Code")) in {"404", "NoSuchKey", "NotFound"}
