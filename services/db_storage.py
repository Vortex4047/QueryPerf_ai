import os
import tempfile
from pathlib import Path


def get_storage_db_path(filename: str = ".queryperf_history.sqlite") -> str:
    """
    Resolves a guaranteed writable path for SQLite storage across local, Docker, and
    serverless environments (such as Vercel or AWS Lambda where the project root is read-only).
    """
    # 1. User/Deployment override via environment variable
    custom_path = os.getenv("QUERYPERF_DB_PATH")
    if custom_path:
        return custom_path

    # 2. Serverless environment detection (Vercel, AWS Lambda, GCP, Cloud Run, Azure)
    serverless_keys = (
        "VERCEL",
        "VERCEL_ENV",
        "VERCEL_URL",
        "VERCEL_REGION",
        "NOW_REGION",
        "AWS_LAMBDA_FUNCTION_NAME",
        "LAMBDA_TASK_ROOT",
        "AWS_EXECUTION_ENV",
        "_HANDLER",
        "K_SERVICE",
        "FUNCTION_TARGET",
    )
    if any(os.getenv(k) for k in serverless_keys):
        return str(Path(tempfile.gettempdir()) / filename)

    # 3. Default to project root ONLY if it is truly writable by attempting a probe write
    project_root = Path(__file__).resolve().parent.parent
    local_path = project_root / filename

    try:
        probe = project_root / f".write_probe_{os.getpid()}"
        probe.touch(exist_ok=True)
        probe.unlink(missing_ok=True)
        return str(local_path)
    except (OSError, PermissionError):
        pass

    return str(Path(tempfile.gettempdir()) / filename)
