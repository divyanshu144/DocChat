import os
import shutil
import tempfile
from pathlib import Path

from app.services.blobs import BlobError, validate_key


class LocalBlobStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / validate_key(key)).resolve()
        if self.root not in path.parents:
            raise BlobError("Invalid storage key")
        return path

    def put_file(self, key: str, path: str | Path) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Copy then rename so a reader never sees a partial object.
        fd, tmp = tempfile.mkstemp(dir=target.parent)
        os.close(fd)
        try:
            shutil.copyfile(path, tmp)
            os.replace(tmp, target)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def fetch_to_path(self, key: str, dest: str | Path) -> None:
        source = self._path(key)
        if not source.is_file():
            raise BlobError("Object not found")
        shutil.copyfile(source, dest)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
