import re
from pathlib import Path
from fastapi import HTTPException

# Dozwolone rozszerzenia
ALLOWED_EXTS = {".pdf", ".txt"}

# Limity
MAX_FILES = 10
MAX_FILE_SIZE = 50 * 1024 * 1024      # 50MB na plik
MAX_TOTAL_SIZE = 200 * 1024 * 1024    # 200MB łączny limit uploadu

# Regexp do sanityzacji nazwy pliku
_safe_name_re = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str) -> str:
    """
    Usuwa podejrzane znaki z nazwy pliku i zabezpiecza przed path traversal.
    """
    base = name.strip().replace("\\", "/").split("/")[-1]
    base = _safe_name_re.sub("_", base)
    return base or "file"


async def save_upload_streamed(upload, dst_path: Path, chunk_size: int = 1024 * 1024) -> int:
    """
    Zapisuje UploadFile na dysk strumieniowo,
    dzięki czemu nie trzymamy całego pliku w RAM.

    Zwraca ilość zapisanych bajtów.
    """
    total = 0
    with dst_path.open("wb") as out:
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            out.write(chunk)
            total += len(chunk)

    # Reset odczytu, jeśli później chcesz używać upload ponownie
    try:
        await upload.seek(0)
    except Exception:
        pass

    return total


def sniff_simple_mime(path: Path) -> str:
    """
    Bardzo prosta heurystyka MIME bez python-magic.
    """
    try:
        head = path.read_bytes()[:8]
    except Exception:
        return "application/octet-stream"

    # Rozpoznanie PDF
    if head.startswith(b"%PDF-"):
        return "application/pdf"

    # Bardzo uproszczona heurystyka TXT
    if all(32 <= b <= 126 or b in (9, 10, 13) for b in head if b != 0):
        return "text/plain"

    return "application/octet-stream"


def validate_file_on_disk(path: Path, original_name: str) -> None:
    """
    Walidacja rozszerzenia, rozmiaru i nagłówka MIME.
    Wywołujesz ją po zapisaniu pliku do tmp.
    """
    ext = path.suffix.lower()

    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=415, detail=f"Niedozwolone rozszerzenie: {ext}")

    size = path.stat().st_size
    if size <= 0:
        raise HTTPException(status_code=400, detail="Pusty plik")
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"Plik '{original_name}' przekracza limit 50MB")

    mime = sniff_simple_mime(path)

    # Spójność rozszerzenie ↔ MIME
    if ext == ".pdf" and mime != "application/pdf":
        raise HTTPException(status_code=415, detail="Plik wygląda na nie-PDF")
    if ext == ".txt" and mime not in {"text/plain", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Plik wygląda na nie-TXT")

    # Dodatkowy check PDF
    if ext == ".pdf":
        with path.open("rb") as f:
            if not f.read(5).startswith(b"%PDF-"):
                raise HTTPException(status_code=415, detail="Nieprawidłowy nagłówek PDF")
