"""Update one KEY=value in the repo's .env without risking the rest of it.

The Strava and Concept2 refresh tokens rotate, so the sync code has to write the new
token back. A plain write_text() can leave a truncated .env behind if the process dies
mid-write, taking every credential with it; writing a temp file and renaming it over
the original is atomic on POSIX. The file is kept mode 600 because it holds secrets.
"""
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / ".env"


def set_env_var(key: str, value: str, path: Path = ENV) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    out = [l for l in lines if not l.startswith(f"{key}=")] + [f"{key}={value}"]
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(out) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    os.environ[key] = value


def require(key: str) -> str:
    """The value of an environment variable, or a plain error naming what to set."""
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"{key} is not set. Copy .env.example to .env and fill it in "
                           f"(see README.md, Setup).")
    return val
