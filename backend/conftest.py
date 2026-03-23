from pathlib import Path
import sys


# Ensure imports resolve from project root so local backend/celery
# does not shadow external `celery` package when tests run from backend/.
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

backend_dir_str = str(BACKEND_DIR)
project_root_str = str(PROJECT_ROOT)

if backend_dir_str in sys.path:
    sys.path.remove(backend_dir_str)

if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)
