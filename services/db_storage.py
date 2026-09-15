import os
import tempfile
from pathlib import Path


def get_storage_db_path(filename: str = ".queryperf_history.sqlite") -> str:
    """
    Resolves a writable path for SQLite storage across local, Docker, and
    serverless environments (such as Vercel or AWS Lambda where the project root is read-only).
    """
    # 1. User/Deployment override via environment variable
    custom_path = os.getenv("QUERYPERF_DB_PATH")
    if custom_path:
        return custom_path

    # 2. Serverless environment detection (Vercel, AWS Lambda, GCP)
    if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME") or os.getenv("LAMBDA_TASK_ROOT"):
        return str(Path(tempfile.gettempdir()) / filename)

    # 3. Default to project root if writable, otherwise fallback to temp directory
    project_root = Path(__file__).resolve().parent.parent
    local_path = project_root / filename

    try:
        if os.access(str(project_root), os.W_OK):
            return str(local_path)
    except Exception:
        pass

    return str(Path(tempfile.gettempdir()) / filename)
