from pathlib import Path

import pytest

from app.services.blobs import BlobError, upload_key, validate_key
from app.services.blobs.local import LocalBlobStore
from app.services.blobs.s3 import S3BlobStore


@pytest.mark.parametrize("bad", ["", "../x", "a/../b", "/abs", "a//b", "a b", "a\x00b", "x" * 600])
def test_validate_key_rejects(bad):
    with pytest.raises(BlobError):
        validate_key(bad)


def test_upload_key_has_no_filename_and_sanitises_suffix():
    assert upload_key("job-1", ".pdf").endswith("/job-1/source.pdf")
    assert upload_key("job-1", "../../etc").endswith("/job-1/source")


def test_local_roundtrip_and_isolation(tmp_path):
    store = LocalBlobStore(tmp_path / "root")
    src = tmp_path / "in.bin"
    src.write_bytes(b"hello")
    store.put_file("uploads/j/source.pdf", src)
    assert store.exists("uploads/j/source.pdf")
    out = tmp_path / "out.bin"
    store.fetch_to_path("uploads/j/source.pdf", out)
    assert out.read_bytes() == b"hello"
    store.delete("uploads/j/source.pdf")
    store.delete("uploads/j/source.pdf")  # idempotent
    assert not store.exists("uploads/j/source.pdf")
    with pytest.raises(BlobError):
        store.fetch_to_path("uploads/j/source.pdf", out)
    assert [p for p in (tmp_path / "root").rglob("*") if p.is_file()] == []  # no temp leftovers


class FakeS3:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def upload_file(self, path, bucket, key):
        self.objects[(bucket, key)] = Path(path).read_bytes()

    def download_file(self, bucket, key, dest):
        from botocore.exceptions import ClientError
        if (bucket, key) not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        Path(dest).write_bytes(self.objects[(bucket, key)])

    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


def test_s3_roundtrip_with_fake_client(tmp_path):
    fake = FakeS3()
    store = S3BlobStore("bkt", client=fake)
    src = tmp_path / "a"
    src.write_bytes(b"data")
    store.put_file("uploads/j/source", src)
    assert store.exists("uploads/j/source") and ("bkt", "uploads/j/source") in fake.objects
    dest = tmp_path / "b"
    store.fetch_to_path("uploads/j/source", dest)
    assert dest.read_bytes() == b"data"
    store.delete("uploads/j/source")
    assert not store.exists("uploads/j/source")
    with pytest.raises(BlobError):
        store.fetch_to_path("uploads/j/source", dest)


def test_s3_rejects_bad_key_before_any_call():
    store = S3BlobStore("bkt", client=object())
    with pytest.raises(BlobError):
        store.exists("../x")


def test_s3_non_missing_errors_propagate():
    from botocore.exceptions import ClientError

    class Denied(FakeS3):
        def head_object(self, Bucket, Key):
            raise ClientError({"Error": {"Code": "403"}}, "HeadObject")

    with pytest.raises(ClientError):
        S3BlobStore("b", client=Denied()).exists("k")
