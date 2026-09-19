from contextlib import contextmanager
from pathlib import Path
import socket, tempfile, uuid


def unique_namespace(prefix: str = "test") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"

def allocate_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); return int(sock.getsockname()[1])

@contextmanager
def isolated_directory():
    with tempfile.TemporaryDirectory(prefix="vision-app-") as value:
        yield Path(value)

def clean_persistence(path: Path) -> None:
    if path.exists():
        for child in path.iterdir():
            if child.is_file(): child.unlink()
