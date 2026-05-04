from dotenv import load_dotenv
import os
import openai
from pathlib import Path
import tempfile
import shutil
from openai import OpenAI
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Body, Depends, Response, APIRouter
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from database.report_repo import save_report
from database.knowledge_service import add_document_to_knowledge_base, check_knowledge_document_hash
from database.user_documents_service import check_user_document_hash
from .utils.files import save_upload_streamed, sanitize_filename, validate_file_on_disk, calculate_file_hash
from .utils.pdf_generator import ReportData, generate_report_pdf
from pydantic import BaseModel
import logging
import json

# Kaskadowe usuwanie dokumentów użytkownika (dokument + powiązane chunki/wektory)
from database.user_documents_deleting import delete_user_document_cascade

# Celery imports (support both package and script-run modes)
try:
    from backend.celery.celery_app import celery_app
    from backend.celery.tasks import (
        parse_and_store,
        parse_and_store_to_knowledge,
        process_user_document,
        process_knowledge_document_full,
        ingest_chunk_file_task,
        ingest_chunk_url_task,
        process_chat_query,
    )
    from backend.celery.report_tasks import generate_report_task
except ImportError:
    from backend.celery.celery_app import celery_app  # type: ignore
    from backend.celery.tasks import (  # type: ignore
        parse_and_store,
        parse_and_store_to_knowledge,
        process_user_document,
        process_knowledge_document_full,
        ingest_chunk_file_task,
        ingest_chunk_url_task,
        process_chat_query,
    )
    from backend.celery.report_tasks import generate_report_task  # type: ignore
from celery.result import AsyncResult

# Redis client do rejestrowania właściciela tasków (ownership check w /status)
import redis as _redis

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
try:
    _redis_client = _redis.Redis.from_url(_REDIS_URL, decode_responses=True)
except Exception:
    _redis_client = None


def _register_task_owner(task_id: str, user_id: str, ttl_seconds: int = 86400) -> None:
    """Zapisz w Redis właściciela taska (dla ownership-check w /status)."""
    if _redis_client is None or not task_id or not user_id:
        return
    try:
        _redis_client.set(f"task:{task_id}:owner", str(user_id), ex=ttl_seconds)
    except Exception:
        pass


def _check_task_owner(task_id: str, user_id: str) -> bool:
    """True jeśli task nie ma właściciela (legacy) lub należy do user_id."""
    if _redis_client is None:
        return True
    try:
        owner = _redis_client.get(f"task:{task_id}:owner")
    except Exception:
        return True
    if owner is None:
        return True
    return str(owner) == str(user_id)


def _rel_task_path(tmp_path: Path, tmp_root: Path) -> str:
    """Zwraca ścieżkę relatywną do tmp_root z ukośnikami POSIX.
    Celery worker w Dockerze rekonstruuje pełną ścieżkę przez WORKER_TMP_ROOT.
    """
    try:
        return tmp_path.relative_to(tmp_root).as_posix()
    except ValueError:
        # Fallback gdy ścieżki nie są w relacji (nie powinno się zdarzać)
        return tmp_path.as_posix()


# Router embeddingów (ZADANIE 2)
try:
    from backend.embeddings import router as embeddings_router
except ImportError:
    from .embeddings import router as embeddings_router  # type: ignore

# Router dokumentów (lista plików użytkownika i bazy wiedzy)
try:
    from backend.documents_getter_endpoints import router as documents_router
except ImportError:
    from .documents_getter_endpoints import router as documents_router  # type: ignore

# Ingestion (scraping + chunking)
from .ingestion import (
    IngestUrlRequest,
    IngestResponse,
    ChunkConfig,
    KeywordFilterConfig,
    fetch_url_text_blocks,
    SourceType,
)
from .ingestion.chunker import make_blocks, chunk_text
from .ingestion.filter import keyword_filter_blocks

# Próbujemy zaimportować parsery - jeśli jesteśmy w pakiecie, użyj względnych importów
try:
    from .parsers.dispatcher import ParserDispatcher
    from .parsers.output_writer import write_result
except ImportError:
    # Jeśli nie jesteśmy w pakiecie (np. uruchomiono main.py bezpośrednio),
    # próbuj importu bezwzględnego
    from parsers.dispatcher import ParserDispatcher
    from parsers.output_writer import write_result

app = FastAPI()

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Podłączenie routera embeddingów (ZADANIE 2 - uporządkowany kod)
app.include_router(embeddings_router)
# Podłączenie routera dokumentów (nowe endpointy listujące)
app.include_router(documents_router)

# wczytuje dane z pliku .env
load_dotenv()

# Authentication routes
try:
    from .auth import router as auth_router, get_current_user
except Exception:
    from auth import router as auth_router, get_current_user

app.include_router(auth_router)

"""
Logger dla /chat/ask
filemode = 'w+' do overwrite przy każdym wywołaniu - nie zmieniać!
"""

logging.basicConfig(filename='logs.log',
                    filemode='w+',
                    format='%(asctime)s,%(msecs)03d %(name)s %(levelname)s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S',
                    level=logging.INFO)

# Leniwa inicjalizacja OpenAI - nie twórz klienta od razu przy imporcie
def get_openai_client():
    global client
    if client is not None:
        return client
        
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("WARNING: OPENAI_API_KEY nie jest ustawiony!")
        return None

    # Sprawdź czy klucz wygląda prawidłowo
    if not api_key.startswith("sk-"):
        print(f"WARNING: Klucz API nie wygląda poprawnie (powinien zaczynać się od 'sk-')")
        return None

    try:
        client = OpenAI(api_key=api_key)
        return client
    except Exception as e:
        print(f"ERROR: Nie można utworzyć klienta OpenAI: {e}")
        return None

# Zmienna do przechowywania klienta OpenAI - inicjalizacja przy pierwszym użyciu
client = None

@app.get("/ping")
def ping():
    return {"message": "pong"}

# Limity multi-upload
MAX_FILES = 10
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

@app.post("/parse")
async def parse_upload(
    files: List[UploadFile] | None = File(None),
    file: UploadFile | None = File(None),
    user = Depends(get_current_user),
):
    """Upload jednego lub wielu plików. Parsowanie odbywa się ASYNCHRONICZNIE przez Celery.
    Zwraca task_id(y) — status pobierasz przez GET /status/{task_id}.
    Limity: max 10 plików, max 50MB każdy.
    """
    incoming: list[UploadFile] = []
    if files:
        incoming.extend(files)
    if file:
        incoming.append(file)

    if not incoming:
        raise HTTPException(status_code=400, detail="No file(s) provided. Use 'files' (multiple) or 'file' (single).")

    if len(incoming) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Too many files. Max allowed: {MAX_FILES}")

    tmp_root = Path(os.getenv("UPLOAD_TMP_ROOT", Path(__file__).resolve().parents[1] / "tmp_uploads"))
    tmp_root.mkdir(parents=True, exist_ok=True)

    enqueued = []
    for f in incoming:
        safe_name = sanitize_filename(f.filename or "file")
        tmp_dir = tempfile.mkdtemp(prefix="upload_", dir=str(tmp_root))
        tmp_path = Path(tmp_dir) / safe_name

        try:
            written = await save_upload_streamed(f, tmp_path)
            if written > MAX_FILE_SIZE:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                enqueued.append({
                    "filename": safe_name,
                    "status": "error",
                    "error": f"File '{safe_name}' exceeds 50MB limit",
                })
                continue

            async_result = parse_and_store.delay(_rel_task_path(tmp_path, tmp_root), safe_name, str(user["id"]))
            _register_task_owner(async_result.id, str(user["id"]))
            enqueued.append({
                "filename": safe_name,
                "status": "queued",
                "task_id": async_result.id,
            })
        except Exception as e:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            enqueued.append({"filename": safe_name, "status": "error", "error": str(e)})

    # Jeśli tylko jeden plik — uprość odpowiedź (BC z poprzednim kontraktem, ale asynchronicznie).
    if len(enqueued) == 1:
        only = enqueued[0]
        if only.get("status") == "queued":
            return {"status": "queued", "task_id": only["task_id"], "filename": only["filename"]}
        return {"status": "error", "filename": only.get("filename"), "error": only.get("error")}

    return {"status": "queued", "count": len(enqueued), "results": enqueued}

# Ingestion endpoints: scraping + keyword filtering + chunking

@app.post("/ingest/chunk/url")
async def ingest_chunk_url(
    body: IngestUrlRequest = Body(...),
    user = Depends(get_current_user),
):
    """
    Asynchronicznie: pobiera stronę WWW, filtruje wg słów kluczowych i chunkuje.
    Zwraca task_id; pełny wynik (IngestResponse) pobierasz przez GET /status/{task_id}.
    """
    async_result = ingest_chunk_url_task.delay(
        body.url,
        body.keywords or None,
        getattr(body, "case_sensitive", False),
        getattr(body, "match_all", False),
        getattr(body, "context_before", 0),
        getattr(body, "context_after", 0),
        getattr(body, "target_tokens", 750),
        getattr(body, "min_tokens", 400),
        getattr(body, "max_tokens", 1200),
        getattr(body, "overlap_tokens", 80),
    )
    _register_task_owner(async_result.id, str(user["id"]))
    return {"task_id": async_result.id, "status": "queued"}


@app.post("/ingest/chunk/file")
async def ingest_chunk_file(
    file: UploadFile = File(...),
    keywords: str | None = Form(None, description="Słowa kluczowe rozdzielone przecinkami"),
    case_sensitive: bool = Form(False),
    match_all: bool = Form(False),
    context_before: int = Form(0),
    context_after: int = Form(0),
    target_tokens: int = Form(750),
    min_tokens: int = Form(400),
    max_tokens: int = Form(1200),
    overlap_tokens: int = Form(80),
    user = Depends(get_current_user),
):
    """
    Asynchronicznie: parsuje plik, filtruje wg słów kluczowych, chunkuje.
    Zwraca task_id; wynik IngestResponse pobierasz przez GET /status/{task_id}.
    """
    tmp_root = Path(os.getenv("UPLOAD_TMP_ROOT", Path(__file__).resolve().parents[1] / "tmp_uploads"))
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="ingest_", dir=str(tmp_root))
    safe_name = sanitize_filename(file.filename or "upload.bin")
    tmp_path = Path(tmp_dir) / safe_name

    try:
        written = await save_upload_streamed(file, tmp_path)
        if written > MAX_FILE_SIZE:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(status_code=413, detail=f"File '{safe_name}' exceeds 50MB limit")

        kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else None

        async_result = ingest_chunk_file_task.delay(
            _rel_task_path(tmp_path, tmp_root),
            safe_name,
            kw_list,
            case_sensitive,
            match_all,
            context_before,
            context_after,
            target_tokens,
            min_tokens,
            max_tokens,
            overlap_tokens,
        )
        _register_task_owner(async_result.id, str(user["id"]))
        return {"task_id": async_result.id, "status": "queued", "filename": safe_name}
    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/openai-status")
def openai_status():
    """Sprawdź czy OpenAI jest skonfigurowane poprawnie."""
    global client

    # Sprawdź czy klucz istnieje w .env
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "status": "error",
            "message": "Brak klucza OPENAI_API_KEY",
            "help": "Dodaj OPENAI_API_KEY do pliku .env",
            "configured": False,
            "validated": False
        }

    # Sprawdź format klucza
    if not api_key.startswith("sk-"):
        return {
            "status": "error",
            "message": "Klucz API ma nieprawidłowy format",
            "help": "Klucz OpenAI powinien zaczynać się od 'sk-'",
            "configured": True,
            "validated": False
        }

    # Próba inicjalizacji i walidacji
    if client is None:
        client = get_openai_client()
    
    if client is None:
        return {
            "status": "error",
            "message": "Klucz API jest nieprawidłowy lub wygasł",
            "help": "Wygeneruj nowy klucz na: https://platform.openai.com/api-keys",
            "configured": True,
            "validated": False
        }

    return {
        "status": "ok",
        "message": "Klient OpenAI zainicjalizowany i zwalidowany",
        "configured": True,
        "validated": True
    }

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    contents = await file.read()
    return {"filename": file.filename}



#celery

@app.post("/process")
async def process_file(
    file: UploadFile = File(...),
    user = Depends(get_current_user)
):
    tmp_root = Path(os.getenv("UPLOAD_TMP_ROOT", Path(__file__).resolve().parents[1] / "tmp_uploads"))
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="task_", dir=str(tmp_root))
    safe_name = sanitize_filename(file.filename or "file")
    tmp_path = Path(tmp_dir) / safe_name

    written = await save_upload_streamed(file, tmp_path)
    if written > MAX_FILE_SIZE:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=413, detail=f"Plik '{safe_name}' przekracza limit 50MB")

    validate_file_on_disk(tmp_path, safe_name)

    async_result = parse_and_store.delay(_rel_task_path(tmp_path, tmp_root), safe_name, str(user["id"]))
    return {"task_id": async_result.id, "status": "queued"}


@app.get("/status/{task_id}")
def get_status(
    task_id: str,
    user = Depends(get_current_user),
):
    """Zwraca rozbudowany status zadania Celery.

    Schemat odpowiedzi:
    {
        "task_id": "...",
        "state": "PENDING|STARTED|PROGRESS|RETRY|SUCCESS|FAILURE",
        "progress": 0-100,
        "stage": "parsing",
        "stage_pl": "Parsowanie pliku",
        "filename": "raport.pdf",
        "attempts": 1,
        "result": {...} | null,
        "error": {"type": "...", "message": "...", "retryable": false} | null,
        "updated_at": "2026-04-16T12:00:00Z"
    }
    """
    from datetime import datetime, timezone

    # Opcjonalny ownership check
    if not _check_task_owner(task_id, str(user["id"])):
        raise HTTPException(status_code=403, detail="Brak dostępu do tego zadania.")

    res = AsyncResult(task_id, app=celery_app)
    now = datetime.now(timezone.utc).isoformat()

    payload: dict = {
        "task_id": task_id,
        "state": res.state,
        "progress": 0,
        "stage": None,
        "stage_pl": None,
        "filename": None,
        "attempts": 1,
        "result": None,
        "error": None,
        "updated_at": now,
    }

    if res.state in {"PENDING", "RECEIVED", "STARTED", "PROGRESS", "RETRY"}:
        info = res.info if isinstance(res.info, dict) else {}
        payload.update({
            "progress": info.get("progress", 0),
            "stage": info.get("step"),
            "stage_pl": info.get("stage_pl"),
            "filename": info.get("filename"),
            "attempts": info.get("attempts", 1 + (res.info or {}).get("retries", 0)
                                 if isinstance(res.info, dict) else 1),
        })
        if res.state == "RETRY" and isinstance(res.info, dict):
            payload["error"] = {
                "type": info.get("exc_type", "RetryError"),
                "message": info.get("exc_message", str(res.info)),
                "retryable": True,
            }
        return payload

    if res.state == "SUCCESS":
        payload["progress"] = 100
        payload["stage_pl"] = "Gotowe"
        payload["result"] = res.result
        return payload

    if res.state == "FAILURE":
        exc = res.result  # wyjątek (instancja lub str)
        exc_type = type(exc).__name__ if exc and not isinstance(exc, str) else "Error"
        exc_msg = str(exc)
        # Stałe nieretryowalne typy
        non_retryable = {"ValueError", "FileNotFoundError", "AuthenticationError",
                         "BadRequestError", "json.JSONDecodeError"}
        payload["error"] = {
            "type": exc_type,
            "message": exc_msg,
            "retryable": exc_type not in non_retryable,
        }
        return payload

    return payload


# ESG Analysis Endpoints

# ---------------------------------------------------------
# REAL ENDPOINTS (NO MOCKS)
# ---------------------------------------------------------

class ReportRequest(BaseModel):
    tag: Optional[str] = None  # Oczekiwane: "Environmental", "Social", "Governance" lub brak


@app.post("/report/generate")
async def generate_report(request: ReportRequest, user=Depends(get_current_user)):
    """
    Asynchroniczne generowanie raportu ESG przez Celery.
    Zwraca task_id; pełny raport JSON pobierasz przez GET /status/{task_id} (pole "result").
    """
    if not user or 'id' not in user:
        raise HTTPException(status_code=401, detail="Brak autoryzacji. Musisz być zalogowany.")

    user_id = str(user['id'])
    async_result = generate_report_task.delay(user_id, request.tag)
    _register_task_owner(async_result.id, user_id)

    return {
        "task_id": async_result.id,
        "status": "queued",
        "message": "Raport jest generowany w tle. Sprawdź /status/{task_id} po wynik.",
    }


@app.get("/report/download/{task_id}")
async def download_report_pdf_from_task(task_id: str, user=Depends(get_current_user)):
    """
    Pobiera wygenerowany raport jako PDF na podstawie ID zakończonego zadania Celery.
    Nie musisz już podawać całego JSON-a, endpoint sam go wyciągnie z wyniku zadania.
    """
    if not user or 'id' not in user:
        raise HTTPException(status_code=401, detail="Brak autoryzacji.")
        
    # Opcjonalny ownership check
    if not _check_task_owner(task_id, str(user["id"])):
        raise HTTPException(status_code=403, detail="Brak dostępu do tego zadania.")

    res = AsyncResult(task_id, app=celery_app)
    if res.state != "SUCCESS":
        raise HTTPException(status_code=400, detail=f"Raport nie jest jeszcze gotowy lub wystąpił błąd. Aktualny status: {res.state}")

    result_data = (res.result or {}).get("data")
    if not result_data:
        raise HTTPException(status_code=404, detail="To zadanie zakończyło się, ale nie zawiera danych raportu (JSON).")

    try:
        # Rzutowanie słownika z pamięci Celery na obiekt Pydantic uzywany przez generację PDF
        report_data = ReportData(**result_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd mapowania danych na PDF: {e}")

    try:
        pdf_bytes = generate_report_pdf(report_data)
        
        headers = {
            "Content-Disposition": f'attachment; filename="raport_{report_data.kategoria}.pdf"'
        }
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
        
    except Exception as e:
        logging.error(f"Błąd generowania PDF: {str(e)}")
        raise HTTPException(status_code=500, detail="Wewnętrzny błąd serwera podczas konwersji do PDF.")

# ====================

@app.post("/knowledge/upload")
async def upload_knowledge_files(
    files: List[UploadFile] = File(...),
    tag: str = Form("general"),
    document_type: str = Form("general"),
    version: str = Form("1.0"),
    user = Depends(get_current_user),
):
    """
    Asynchroniczne przesyłanie plików do bazy wiedzy (parse + chunk + embed przez Celery).
    Zwraca listę {filename, task_id} — status sprawdzaj przez GET /status/{task_id}.
    Tylko admin.
    """
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can upload knowledge documents")

    if not files:
        raise HTTPException(status_code=400, detail="Brak przesłanych plików.")

    tmp_root = Path(os.getenv("UPLOAD_TMP_ROOT", Path(__file__).resolve().parents[1] / "tmp_uploads"))
    tmp_root.mkdir(parents=True, exist_ok=True)

    enqueued = []
    for upload_file in files:
        safe_name = sanitize_filename(upload_file.filename or "unknown")
        tmp_dir = tempfile.mkdtemp(prefix="kb_upload_", dir=str(tmp_root))
        tmp_path = Path(tmp_dir) / safe_name

        try:
            written = await save_upload_streamed(upload_file, tmp_path)
            if written > MAX_FILE_SIZE:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                enqueued.append({
                    "filename": safe_name,
                    "status": "error",
                    "error": f"Plik '{safe_name}' przekracza limit 50MB",
                })
                continue

            file_hash = calculate_file_hash(tmp_path)
            if check_knowledge_document_hash(file_hash):
                shutil.rmtree(tmp_dir, ignore_errors=True)
                enqueued.append({
                    "filename": safe_name,
                    "status": "error",
                    "error": "Ten dokument został już wgrany do bazy wiedzy (duplikat).",
                })
                continue

            async_result = process_knowledge_document_full.delay(
                _rel_task_path(tmp_path, tmp_root),
                safe_name,
                tag=tag,
                document_type=document_type,
                version=version,
                uploaded_by=str(user["id"]),
                file_hash=file_hash,
            )
            _register_task_owner(async_result.id, str(user["id"]))
            enqueued.append({
                "filename": safe_name,
                "status": "queued",
                "task_id": async_result.id,
            })
        except Exception as e:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            enqueued.append({"filename": safe_name, "status": "error", "error": str(e)})

    return {"results": enqueued}



@app.post("/knowledge/parse-and-store")
async def parse_and_store_knowledge(
    file: UploadFile = File(...),
    tag: str = Form("general"),
    document_type: str = Form("general"),
    version: str = Form("1.0"),
    user = Depends(get_current_user)
):
    # tylko admin
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can parse and store knowledge docums")
    """
    INTEGRACJA PARSERÓW Z BAZĄ WIEDZY (ZADANIE 1).

    Przyjmuje plik (PDF/DOCX/Excel), parsuje go, ekstrahuje tekst,
    automatycznie chunkuje i zapisuje do Supabase (knowledge_documents + knowledge_chunks).

    UWAGA: To zadanie asynchroniczne (Celery) - zwraca task_id.

    Flow:
    1. Upload pliku → tymczasowy katalog
    2. Celery task: parse_and_store_to_knowledge
    3. Parser wyciąga tekst
    4. Chunker dzieli na fragmenty
    5. Zapis do Supabase (bez embeddingów)

    Query /status/{task_id} aby sprawdzić postęp.
    """
    # Przygotowanie pliku tymczasowego
    tmp_root = Path(os.getenv("UPLOAD_TMP_ROOT", Path(__file__).resolve().parents[1] / "tmp_uploads"))
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="kb_task_", dir=str(tmp_root))
    safe_name = sanitize_filename(file.filename or "file")
    tmp_path = Path(tmp_dir) / safe_name

    # Zapis pliku
    written = await save_upload_streamed(file, tmp_path)
    if written > MAX_FILE_SIZE:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=413, detail=f"Plik '{safe_name}' przekracza limit 50MB")

    validate_file_on_disk(tmp_path, safe_name)

    file_hash = calculate_file_hash(tmp_path)
    if check_knowledge_document_hash(file_hash):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=409, detail="Ten dokument został już wgrany do bazy wiedzy (duplikat).")

    # Uruchomienie taska Celery
    async_result = parse_and_store_to_knowledge.delay(
        _rel_task_path(tmp_path, tmp_root),
        safe_name,
        tag=tag,
        document_type=document_type,
        version=version,
        uploaded_by=str(user["id"]),
        file_hash=file_hash
    )

    return {
        "task_id": async_result.id,
        "status": "queued",
        "message": "Plik został wysłany do parsowania i zapisu w bazie wiedzy. Sprawdź /status/{task_id}"
    }


# ============================================================
# ENDPOINTY EMBEDDINGÓW PRZENIESIONE DO: backend/embeddings/router.py
# Dostępne przez app.include_router(embeddings_router)
#
# Endpointy:
# - POST /embeddings/generate
# - POST /embeddings/generate-for-document
# - POST /embeddings/generate-for-tag
# - POST /embeddings/generate-all
# - GET /embeddings/status
# ============================================================


# ==========================================
#  USER DOCUMENTS (RAG UŻYTKOWNIKA)
# ==========================================

# Import serwisu, który przed chwilą stworzyliśmy
try:
    from backend.services.user_document_service import process_and_save_user_document
except ImportError:
    from database.user_documents_service import process_and_save_user_document


@app.post("/user/documents/upload")
async def upload_user_document(
    file: UploadFile = File(...),
    tag: str = Form("project_x"),
    user=Depends(get_current_user),
):
    """
    Asynchroniczny upload dokumentu użytkownika (parse + chunk + embed przez Celery).
    Zwraca task_id; wynik sprawdzasz przez GET /status/{task_id}.
    """
    if not user or 'id' not in user:
        raise HTTPException(status_code=401, detail="User ID not found")

    user_id = str(user['id'])

    tmp_root = Path(os.getenv("UPLOAD_TMP_ROOT", Path(__file__).resolve().parents[1] / "tmp_uploads"))
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="user_rag_", dir=str(tmp_root))
    safe_name = sanitize_filename(file.filename or "uploaded_doc")
    tmp_path = Path(tmp_dir) / safe_name

    try:
        written = await save_upload_streamed(file, tmp_path)
        if written > MAX_FILE_SIZE:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(status_code=413, detail=f"Plik '{safe_name}' przekracza limit 50MB")

        file_hash = calculate_file_hash(tmp_path)
        if check_user_document_hash(user_id, file_hash):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(status_code=409, detail="Ten dokument został już przez Ciebie wgrany (duplikat).")

        async_result = process_user_document.delay(_rel_task_path(tmp_path, tmp_root), safe_name, user_id, tag, file_hash)
        _register_task_owner(async_result.id, user_id)

        return {
            "task_id": async_result.id,
            "status": "queued",
            "filename": safe_name,
            "message": "Dokument jest przetwarzany w tle. Sprawdź /status/{task_id} po wynik.",
        }
    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))


class DeleteUserDocumentRequest(BaseModel):
    document_id: str


@app.post("/user/documents/delete")
def delete_user_document_endpoint(
    body: DeleteUserDocumentRequest,
    user=Depends(get_current_user),
):
    """Kasuje dokument usera oraz wszystkie powiązane z nim chunki/wektory.

    Endpoint jest cienki: jedynie bierze user_id z tokena.
    Walidacja właściciela dokumentu i sama kaskada jest w delete_user_document_cascade().
    """
    if not user or "id" not in user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return delete_user_document_cascade(user_id=str(user["id"]), document_id=str(body.document_id))


# =============== TEST EMBEDDINGU ==============
# Model dla testu
class EmbeddingTestInput(BaseModel):
    text: str

# Usuwam swój tymczasowy endpoint test/embedding, bo patryk ma go w swoim panelu administracyjnym (router.py)
# ========= KONIEC TESTU EMBEDDINGU =========

# ======= ENDPOINT DO TESTU FINALNEGO ZAPYTANIA DO MODELU ========
# Import funkcji Damiana (Retrieval)
from backend.RAG.rag_retriever import retrieve_context_async

# Import Twojej funkcji (Prompt Injection)
from backend.RAG.prompt_builder import construct_prompt

# ==========================================
#  RAG ENDPOINT (Full Pipeline)
# ==========================================

from pydantic import BaseModel
from typing import Optional

# Importujemy logikę Damiana/Patryka (Retrieval)
try:
    from backend.RAG.rag_retriever import retrieve_context_async
except ImportError:
    from .RAG.rag_retriever import retrieve_context_async  # type: ignore

# Importujemy Prompt Builder
try:
    from backend.RAG.prompt_builder import construct_prompt
except ImportError:
    from .RAG.prompt_builder import construct_prompt  # type: ignore

class ChatRequest(BaseModel):
    query: Optional[str] = None
    tag: Optional[str] = None
    session_id: Optional[str] = None

from database.chat_repository import create_chat_session, add_chat_message, get_chat_sessions, get_chat_messages, delete_chat_session

@app.get("/chat/sessions")
def get_sessions(limit: int = 50, offset: int = 0, user = Depends(get_current_user)):
    """Pobiera listę sesji konwersacji użytkownika."""
    if not user or 'id' not in user:
        raise HTTPException(status_code=401, detail="Brak autoryzacji.")
    return get_chat_sessions(str(user['id']), limit, offset)


@app.delete("/chat/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, user = Depends(get_current_user)):
    """Usuwa sesję czatu użytkownika wrąz z całą historią wiadomości."""
    if not user or 'id' not in user:
        raise HTTPException(status_code=401, detail="Brak autoryzacji.")
    
    success = delete_chat_session(str(user['id']), session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Nie znaleziono sesji lub nie masz do niej dostępu.")
    return None


@app.get("/chat/sessions/{session_id}/history")
def get_session_history(session_id: str, limit: int = 50, offset: int = 0, user = Depends(get_current_user)):
    """Pobiera chronologiczną historię danej konwersacji."""
    if not user or 'id' not in user:
        raise HTTPException(status_code=401, detail="Brak autoryzacji.")
    # TODO: weryfikacja czy user_id jest wlascicielem sesji. Tu uprotek.
    return get_chat_messages(session_id, limit, offset)


@app.post("/chat/ask")
async def ask_chat(request: ChatRequest, user = Depends(get_current_user)):
    """
    Endpoint czatu (Celery Odtworzony RAG). Zwraca task_id.
    Służy wyłącznie do odpowiadania na pytania użytkownika na podstawie bazy wektorowej.
    """
    if not user or 'id' not in user:
        raise HTTPException(status_code=401, detail="Brak autoryzacji.")

    user_id = str(user['id'])

    if not request.query or not request.query.strip():
        raise HTTPException(
            status_code=400,
            detail="Pytanie nie może być puste."
        )

    final_query = request.query.strip()
    search_tag = request.tag if request.tag else None
    
    # 1. Obsługa sesji
    session_id = request.session_id
    if not session_id:
        title = final_query[:50] + ("..." if len(final_query) > 50 else "")
        session_id = create_chat_session(user_id=user_id, title=title)

    # 2. Zapis wiadomości jako użytkownik
    add_chat_message(session_id=session_id, role="user", content=final_query)

    # 3. Wysyłamy zadanie w tło
    async_result = process_chat_query.delay(session_id, user_id, final_query, search_tag)
    _register_task_owner(async_result.id, user_id)

    return {
        "status": "queued",
        "task_id": async_result.id,
        "session_id": session_id,
        "message": "Pytanie przetwarzane w tle. Sprawdź status zadania.",
    }

# =========== ENDPOINT GET DLA WSZYSTKICH RAPORTÓW USERA ===============
from database.report_repo import get_reports_by_user, get_report_by_id
@app.get("/reports/user", tags=["Reports"])
async def get_user_reports_endpoint(user_id: str):
    """Pobiera skróconą listę wszystkich raportów użytkownika."""
    try:
        rows = get_reports_by_user(user_id)
        # rows to lista krotek (id, report_type, created_at) zdefiniowana w report_repo.py
        reports = [
            {"id": r[0], "report_type": r[1], "created_at": r[2]}
            for r in rows
        ]
        return {"status": "success", "reports": reports}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd bazy: {str(e)}")

# =========== ENDPOINT GET DLA RAPORTU PO RAPORT_ID (Z NOWĄ KOLUMNĄ USED_CHUNKS) - JSON DLA FRONT'U ===============
@app.get("/reports/{report_id}", tags=["Reports"])
async def get_single_report_endpoint(report_id: str, user_id: str):
    """Pobiera pełen wygenerowany JSON oraz powiązane chunki źródłowe."""
    try:
        report = get_report_by_id(report_id, user_id)
        if not report:
            raise HTTPException(status_code=404, detail="Raport nie istnieje lub brak dostępu.")

        # 1. Parsowanie stringa AI do JSON-a
        try:
            parsed_content = json.loads(report["response_text"] or "{}")
        except json.JSONDecodeError:
            parsed_content = {"error": "Błąd dekodowania JSON ze stringa."}

        # 2. Parsowanie chunków
        used_chunks = []
        if report["used_chunks"]:
            try:
                used_chunks = json.loads(report["used_chunks"])
            except json.JSONDecodeError:
                used_chunks = []

        return {
            "status": "success",
            "metadata": {
                "id": report["id"],
                "report_type": report["report_type"],
                "created_at": report["created_at"]
            },
            "content": parsed_content,
            "used_chunks": used_chunks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Wewnętrzny błąd serwera: {str(e)}")