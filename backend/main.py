from dotenv import load_dotenv
import os
import openai
from pathlib import Path
import tempfile
import shutil
from openai import OpenAI
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Body, Depends
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from database.report_repo import save_report
from database.knowledge_service import add_document_to_knowledge_base
from .utils.files import save_upload_streamed, sanitize_filename, validate_file_on_disk
from pydantic import BaseModel
import logging

# Kaskadowe usuwanie dokumentów użytkownika (dokument + powiązane chunki/wektory)
from database.user_documents_deleting import delete_user_document_cascade

# Celery imports (support both package and script-run modes)
try:
    from backend.celery.celery_app import celery_app
    from backend.celery.tasks import parse_and_store, parse_and_store_to_knowledge
except ImportError:
    from backend.celery.celery_app import celery_app  # type: ignore
    from backend.celery.tasks import parse_and_store, parse_and_store_to_knowledge  # type: ignore
from celery.result import AsyncResult

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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
    """Upload one or many files, parse server-side, and write results into output_test_parser/.
    - Accepts either multiple `files` or single `file` for backward/simple usage.
    - Enforces: max 10 files, max 50MB each.
    """
    # Zbierz wejście w listę
    incoming: list[UploadFile] = []
    if files:
        incoming.extend(files)
    if file:
        incoming.append(file)

    if not incoming:
        raise HTTPException(status_code=400, detail="No file(s) provided. Use 'files' (multiple) or 'file' (single).")

    if len(incoming) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Too many files. Max allowed: {MAX_FILES}")

    dispatcher = ParserDispatcher()
    project_root = Path(__file__).resolve().parents[1]
    out_root = project_root / "output_test_parser"

    # Jeśli tylko jeden plik — zachowaj dotychczasowy format odpowiedzi
    if len(incoming) == 1:
        f = incoming[0]
        tmp_dir = tempfile.mkdtemp(prefix="upload_")
        tmp_path = Path(tmp_dir) / f.filename
        try:
            data = await f.read()
            if len(data) > MAX_FILE_SIZE:
                raise HTTPException(status_code=413, detail=f"File '{f.filename}' exceeds 50MB limit")
            tmp_path.write_bytes(data)

            result = dispatcher.parse(tmp_path)
            manifest = write_result(result, out_root)
            try:
                save_report(
                    user_id=str(user["id"]),
                    input_text=str(f.filename),
                    response_text="Plik przetworzony pomyślnie",
                    report_type="parse_result",
                )
            except Exception:
                # Nie zrywaj odpowiedzi API, jeśli DB chwilowo niedostępna
                pass

            return {"status": "ok", "manifest": manifest}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        finally:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    # Wiele plików — agreguj wyniki per plik
    results = []
    for f in incoming:
        tmp_dir = tempfile.mkdtemp(prefix="upload_")
        tmp_path = Path(tmp_dir) / f.filename
        item = {"filename": f.filename}
        try:
            data = await f.read()
            if len(data) > MAX_FILE_SIZE:
                item["status"] = "error"
                item["error"] = "File exceeds 50MB limit"
                results.append(item)
                continue

            tmp_path.write_bytes(data)
            result = dispatcher.parse(tmp_path)
            manifest = write_result(result, out_root)

            # DB
            try:
                report_id = save_report(
                    user_id=str(user["id"]),
                    input_text=str(f.filename),
                    response_text="Plik przetworzony pomyślnie",
                    report_type="parse_result",
                )
                item["report_id"] = report_id
            except Exception:
                pass

            item["status"] = "ok"
            item["manifest"] = manifest
        except Exception as e:
            item["status"] = "error"
            item["error"] = str(e)
        finally:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
            results.append(item)

    return {"status": "ok", "count": len(results), "results": results}

# Ingestion endpoints: scraping + keyword filtering + chunking

@app.post("/ingest/chunk/url")
async def ingest_chunk_url(body: IngestUrlRequest = Body(...)):
    """
    Pobiera stronę WWW (HTML), czyści do tekstu, następnie filtruje wg słów kluczowych
    i dzieli na fragmenty (chunking) z overlapem. Zwraca listę chunków.
    """
    try:
        blocks = fetch_url_text_blocks(body.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Fetch error: {e}")

    kcfg, ccfg = body.to_configs()
    # jeśli brak keywordów -> weź całe bloki
    if body.keywords:
        filtered_blocks, kept = keyword_filter_blocks(blocks, kcfg)
    else:
        filtered_blocks, kept = blocks, list(range(len(blocks)))

    # Połącz i ponownie pocięte zgodnie z regułami chunkera
    joined = "\n\n".join(filtered_blocks)
    chunks_models = chunk_text(joined, ccfg)

    resp = IngestResponse(
        source_type=SourceType.url,
        source=body.url,
        total_blocks=len(blocks),
        chunks=chunks_models,
        notes=(
            "Brak dopasowań dla słów kluczowych" if body.keywords and not filtered_blocks else None
        ),
    )
    return resp


@app.post("/ingest/chunk/file")
async def ingest_chunk_file(
    file: UploadFile = File(...),
    # prosty, elastyczny input z formularza (opcjonalny)
    keywords: str | None = Form(None, description="Słowa kluczowe rozdzielone przecinkami"),
    case_sensitive: bool = Form(False),
    match_all: bool = Form(False),
    context_before: int = Form(0),
    context_after: int = Form(0),
    target_tokens: int = Form(750),
    min_tokens: int = Form(400),
    max_tokens: int = Form(1200),
    overlap_tokens: int = Form(80),
):
    dispatcher = ParserDispatcher()

    # Zapis tymczasowy pliku i parsowanie istniejącym modułem
    tmp_dir = tempfile.mkdtemp(prefix="ingest_")
    tmp_path = Path(tmp_dir) / (file.filename or "upload.bin")
    try:
        data = await file.read()
        if len(data) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail=f"File '{file.filename}' exceeds 50MB limit")
        tmp_path.write_bytes(data)

        parsed = dispatcher.parse(tmp_path)
        text = parsed.text or ""
        if not text and parsed.pages:
            text = "\n\n".join(parsed.pages)
        if not text:
            raise HTTPException(status_code=400, detail="Brak tekstu do przetworzenia z pliku")

        blocks = make_blocks(text)

        kw_list = []
        if keywords:
            kw_list = [k.strip() for k in keywords.split(",") if k.strip()]

        kcfg = KeywordFilterConfig(
            keywords=kw_list,
            case_sensitive=case_sensitive,
            match_all=match_all,
            context_before=context_before,
            context_after=context_after,
        )
        ccfg = ChunkConfig(
            target_tokens=target_tokens,
            min_tokens=min_tokens,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )

        if kw_list:
            filtered_blocks, kept = keyword_filter_blocks(blocks, kcfg)
        else:
            filtered_blocks, kept = blocks, list(range(len(blocks)))

        joined = "\n\n".join(filtered_blocks)
        chunks_models = chunk_text(joined, ccfg)

        resp = IngestResponse(
            source_type=SourceType.file,
            source=str(file.filename),
            total_blocks=len(blocks),
            chunks=chunks_models,
            notes=(
                "Brak dopasowań dla słów kluczowych" if kw_list and not filtered_blocks else None
            ),
        )
        return resp
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


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

    async_result = parse_and_store.delay(str(tmp_path), safe_name, str(user["id"]))
    return {"task_id": async_result.id, "status": "queued"}


@app.get("/status/{task_id}")
def get_status(
    task_id: str,
    user = Depends(get_current_user)
):
    """Zwraca status zadania Celery i metadane postepu.
    - PENDING/RECEIVED/STARTED/PROGRESS/SUCCESS/FAILURE
    - meta: np. {step: "parsing"}
    """
    res = AsyncResult(task_id, app=celery_app)
    payload = {
        "task_id": task_id,
        "state": res.state,
    }
    # W trakcie: meta
    if res.state in {"PENDING", "RECEIVED", "STARTED", "PROGRESS", "RETRY"}:
        info = res.info if isinstance(res.info, dict) else None
        if info:
            payload["meta"] = info
        return payload
    
    # Sukces: pelny wynik
    if res.state == "SUCCESS":
        payload["result"] = res.result
        return payload

    if res.state == "FAILURE":
        payload["error"] = str(res.info)
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
    Zunifikowany endpoint do generowania ustrukturyzowanych raportów ESG (JSON).
    Wymaga zalogowanego użytkownika. Szuka danych w bazie wektorowej przypisanych do tego usera.
    """
    # 1. Twarda autoryzacja
    if not user or 'id' not in user:
        raise HTTPException(status_code=401, detail="Brak autoryzacji. Musisz być zalogowany.")

    user_id = str(user['id'])

    # 2. Logika Tagów (Jeśli brak tagu -> wymuszamy ogólne ESG)
    target_tag = request.tag.strip() if request.tag and request.tag.strip() else "ESG"
    db_filter_tag = request.tag if request.tag and request.tag.strip() else None

    search_query = f"Kluczowe wskaźniki, twarde dane liczbowe, polityki i statystyki dla obszaru: {target_tag}"

    # 3. Retrieval - pobranie z bazy wektorowej (Przekazujemy user_id do filtra!)
    found_chunks = await retrieve_context_async(
        query=search_query,
        user_id=user_id,  # <--- KRYTYCZNE: Baza musi szukać tylko w plikach tego użytkownika
        match_count=15,
        filter_tag=db_filter_tag
    )

    # 4. Obsługa braku danych
    if not found_chunks:
        return {
            "status": "partial_success",
            "kategoria": target_tag,
            "message": "⚠️ Brak danych w dokumentach źródłowych dla tego obszaru.",
            "data": None
        }

    # 5. Dynamiczny Prompt wymuszający format JSON
    context_text = "\n\n".join([f"[Fragment {i + 1}]: {chunk}" for i, chunk in enumerate(found_chunks)])

    report_prompt = f"""Przeanalizuj poniższe fragmenty dokumentacji i wygeneruj twardy, ustrukturyzowany raport dla obszaru: {target_tag}.

DANE WEJŚCIOWE (Kontekst z bazy wektorowej):
{context_text}

INSTRUKCJA:
1. Zwróć dane WYŁĄCZNIE w formacie poprawnego JSON.
2. Skup się na twardych danych, jednostkach (np. tCO2e, %, liczba osób) i politykach.
3. Jeśli w danych wejściowych nie ma informacji o danym podpunkcie, wstaw wartość `null`.
4. POD ŻADNYM POZOREM nie zmyślaj danych. Opieraj się tylko na dostarczonym kontekście.

OCZEKIWANA STRUKTURA JSON:
{{
  "kategoria": "{target_tag}",
  "kluczowe_wskazniki": {{}},
  "polityki_i_procedury": [],
  "zidentyfikowane_ryzyka": [],
  "podsumowanie": "Krótkie, jednozdaniowe podsumowanie."
}}
"""

    # 6. Wywołanie OpenAI
    openai_client = get_openai_client()
    if not openai_client:
        raise HTTPException(status_code=500, detail="Brak klucza API.")

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Jesteś analitykiem ESG. Twój jedyny język to poprawny JSON."},
                {"role": "user", "content": report_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=25.0
        )

        import json
        raw_ai_response = response.choices[0].message.content
        report_json = json.loads(raw_ai_response)

    except openai.APITimeoutError:
        raise HTTPException(status_code=504, detail="Timeout (504): Serwer AI nie wygenerował raportu w czasie.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd generowania raportu: {str(e)}")

    # 7. Zapis do bazy
    try:
        save_report(
            user_id=user_id,
            input_text=f"Generowanie raportu: {target_tag}",
            response_text=raw_ai_response,
            report_type="unified_esg_report"
        )
    except Exception as e:
        logging.warning(f"Nie udało się zapisać raportu do bazy: {e}")

    return {
        "status": "success",
        "mode": "report_generation",
        "kategoria": target_tag,
        "rag_used": True,
        "data": report_json
    }
# ====================

@app.post("/knowledge/upload")
async def upload_knowledge_files(
    files: List[UploadFile] = File(...),
    tag: str = Form("general"),
    document_type: str = Form("general"),
    version: str = Form("1.0"),
    user = Depends(get_current_user)
):
    #tylko admin moze update knowledge
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can upload knowledge documents")
    """
    Endpoint do przesyłania plików do bazy wiedzy ("knowledge_documents", nie "knowledge_chunks"!!!!).
    Parsuje pliki, wyciąga tekst i zapisuje do Supabase (dokumenty + chunki).
    """
    if not files:
        raise HTTPException(status_code=400, detail="Brak przesłanych plików.")

    results = []
    dispatcher = ParserDispatcher()

    # Tworzymy folder tymczasowy
    tmp_dir = Path(tempfile.mkdtemp(prefix="knowledge_upload_"))
    try:
        for upload_file in files:
            safe_name = sanitize_filename(upload_file.filename or "unknown")
            tmp_path = tmp_dir / safe_name

            await save_upload_streamed(upload_file, tmp_path)

            try:
                parse_result = dispatcher.parse(tmp_path)
                raw_text = parse_result.text

                if not raw_text.strip():
                    results.append({
                        "file": safe_name,
                        "status": "skipped",
                        "reason": "Brak wyodrębnionego tekstu."
                    })
                    continue

                db_res = await add_document_to_knowledge_base(
                    title=safe_name,
                    source=f"upload:{safe_name}",
                    raw_text=raw_text,
                    tag=tag,
                    document_type=document_type,
                    version=version,
                    uploaded_by=str(user["id"])
                )

                results.append({
                    "file": safe_name,
                    "status": "success",
                    "document_id": db_res["document_id"]
                })

            except Exception as e:
                results.append({
                    "file": safe_name,
                    "status": "error",
                    "detail": str(e)
                })

    finally:
        # Usuwamy pliki tymczasowe
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"results": results}



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

    # Uruchomienie taska Celery
    async_result = parse_and_store_to_knowledge.delay(
        str(tmp_path),
        safe_name,
        tag=tag,
        document_type=document_type,
        version=version,
        uploaded_by=str(user["id"])
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
        tag: str = Form("project_x"),  # Użytkownik może otagować plik (np. nazwą projektu)
        user=Depends(get_current_user)
):
    """
    Kompleksowy endpoint dla użytkownika:
    1. Upload pliku.
    2. Parsowanie tekstu (PDF/DOCX -> TXT).
    3. Zapis do bazy (user_documents).
    4. Chunking + Embedding (user_document_chunks).
    """

    # 1. Walidacja usera
    if not user or 'id' not in user:
        raise HTTPException(status_code=401, detail="User ID not found")

    user_id = user['id']

    # 2. Przygotowanie pliku i parsowanie
    dispatcher = ParserDispatcher()

    # Tworzymy folder tymczasowy
    tmp_dir = Path(tempfile.mkdtemp(prefix="user_rag_"))
    try:
        safe_name = sanitize_filename(file.filename or "uploaded_doc")
        tmp_path = tmp_dir / safe_name

        # Zapis na dysk
        await save_upload_streamed(file, tmp_path)

        # Ekstrakcja tekstu (używamy Waszych parserów)
        parse_result = dispatcher.parse(tmp_path)
        raw_text = parse_result.text

        if not raw_text or not raw_text.strip():
            raise HTTPException(status_code=400, detail="Nie udało się wydobyć tekstu z pliku.")

        # 3. Wywołanie serwisu (Logika biznesowa + Embeddingi)
        # To tutaj dzieje się magia, którą napisałeś w user_document_service.py
        result = await process_and_save_user_document(
            user_id=str(user_id),
            filename=safe_name,
            raw_text=raw_text,
            file_type=tmp_path.suffix.replace(".", ""),  # np. 'pdf'
            tag=tag
        )

        return {
            "status": "success",
            "filename": safe_name,
            "details": result
        }

    except Exception as e:
        print(f"Error processing user document: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Sprzątanie
        shutil.rmtree(tmp_dir, ignore_errors=True)


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
    query: Optional[str] = None  # <-- ZMIANA: Teraz query może być puste (None)
    tag: Optional[str] = None


@app.post("/chat/ask")
async def ask_chat(request: ChatRequest):
    """
    Czysty endpoint czatu Q&A.
    Służy wyłącznie do odpowiadania na pytania użytkownika na podstawie bazy wektorowej.
    """

    # 1. TWARDA WALIDACJA PYTANIA
    if not request.query or not request.query.strip():
        raise HTTPException(
            status_code=400,
            detail="Pytanie nie może być puste. Aby wygenerować raport, użyj dedykowanego endpointu."
        )

    final_query = request.query.strip()

    # Jeśli frontend nie przyśle tagu, ustawiamy None (brak filtru -> szukamy we wszystkich otagowanych i nieotagowanych)
    search_tag = request.tag if request.tag else None

    # --- KROK 1: RETRIEVAL ---
    found_chunks = await retrieve_context_async(
        query=search_query,
        user_id=user_id,  # <--- KRYTYCZNE: Baza musi szukać tylko w plikach tego użytkownika
        match_count=20,  # <-- Zwiększamy liczbę fragmentów, żeby złapać szerszy kontekst
        match_threshold=0.25,
        # Drastyczne obniżenie progu tylko dla raportów (Zgarnianie danych szeroką siecią)
        filter_tag=db_filter_tag
    )

    # --- KROK 2: PROMPT BUILDING & FALLBACK ---
    if not found_chunks:
        # FALLBACK: Brak wyników w bazie danych dla zadanego pytania
        final_prompt = f"""
SYSTEM ROLE:
Jesteś asystentem AI ds. ESG. Odpowiadasz na pytania użytkowników.

SYTUACJA KRYTYCZNA:
Użytkownik zadał pytanie, ale w dostarczonych dokumentach NIE ZNALEZIONO żadnych informacji na ten temat.

USER QUESTION:
{final_query}

INSTRUCTIONS:
1. Rozpocznij odpowiedź od dokładnego ostrzeżenia: "⚠️ **Brak danych w załączonych dokumentach.** W dostarczonej bazie wiedzy nie znalazłem informacji na ten temat. Poniższa odpowiedź opiera się na ogólnej wiedzy."
2. Następnie udziel profesjonalnej, teoretycznej odpowiedzi na pytanie.
3. POD ŻADNYM POZOREM nie wymyślaj statystyk ani faktów dotyczących konkretnej firmy.
"""
    else:
        # STANDARD FLOW: Mamy kontekst z bazy.
        final_prompt = construct_prompt(
            query=final_query,
            context_chunks=found_chunks,
            focused_tag=search_tag
        )

    # --- KROK 3: WYSŁANIE DO OPENAI Z ZABEZPIECZENIEM TIMEOUT ---
    openai_client = get_openai_client()
    if not openai_client:
        raise HTTPException(status_code=500, detail="Brak klucza OPENAI_API_KEY w .env")

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": final_prompt}
            ],
            temperature=0.4,
            timeout=15.0
        )
        ai_answer = response.choices[0].message.content

    except openai.APITimeoutError:
        raise HTTPException(status_code=504,
                            detail="Timeout (504): Serwer AI nie odpowiedział w wyznaczonym czasie (15s).")
    except openai.RateLimitError:
        raise HTTPException(status_code=429, detail="Rate Limit (429): Przekroczono limit zapytań OpenAI.")
    except openai.APIError as e:
        raise HTTPException(status_code=502, detail=f"Bad Gateway (502): Awaria dostawcy OpenAI: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Wewnętrzny błąd serwera AI: {str(e)}")

    # --- KROK 4: OUTPUT ---
    logging.info(f"Input Tag: {search_tag}")
    logging.info(f"\n\nFinal Query:\n{final_query}")
    logging.info(f"\n\nFound Chunks:\n{found_chunks}")
    logging.info(f"\n\nAI Answer:\n{ai_answer}")

    return {
        "status": "success",
        "mode": "chat_mode",
        "rag_used": bool(found_chunks),
        "final_query_used": final_query,
        "applied_filter": search_tag or "Brak (przeszukano całą bazę)",
        "ai_answer": ai_answer,
        "debug_prompt": final_prompt
    }
