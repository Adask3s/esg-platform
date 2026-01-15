from dotenv import load_dotenv
import os
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

# wczytuje dane z pliku .env
load_dotenv()

# Authentication routes
try:
    from .auth import router as auth_router, get_current_user
except Exception:
    from auth import router as auth_router, get_current_user

app.include_router(auth_router)

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

            # Zapis do DB (user_id tymczasowo 1; nazwa pliku w input_text; stały response_text)
            try:
                save_report(
                    user_id=1,
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
                    user_id=1,
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

    async_result = parse_and_store.delay(str(tmp_path), safe_name, 1)
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

@app.post("/analyze-social")
async def analyze_social(
    report_path: str,
    user = Depends(get_current_user)
):
    """
    PRODUKCYJNY ENDPOINT SOCIAL (S).
    Wymaga klucza OpenAI API. Analizuje plik text.txt ze wskazanej ścieżki.
    """
    # 1. Konfiguracja klienta OpenAI
    openai_client = get_openai_client()
    if openai_client is None:
        raise HTTPException(
            status_code=500,
            detail="OpenAI API key is missing. Configure .env file."
        )

    # 2. Walidacja ścieżki
    report_dir = Path(report_path)
    if not report_dir.exists():
        raise HTTPException(status_code=404, detail=f"Directory not found: {report_path}")

    text_file = report_dir / "text.txt"
    if not text_file.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {text_file}")

    full_text = text_file.read_text(encoding="utf-8")

    # 3. Prompt Systemowy (Social)
    social_prompt = f"""Przeanalizuj poniższy tekst raportu budowlanego/ESG i wyciągnij dane dla kategorii SOCIAL (S).

DANE WEJŚCIOWE:
{full_text[:50000]}  # Ograniczenie znaków dla bezpieczeństwa tokenów

INSTRUKCJA:
Wygeneruj raport w formacie JSON zawierający kluczowe wskaźniki społeczne.
Skup się na liczbach (liczba wypadków, liczba przeszkolonych osób, % kobiet).
Jeśli brak danych, wpisz null.

OCZEKIWANY FORMAT JSON:
{{
  "kategoria": "Social",
  "bhp": {{
    "wypadki_ciezkie": 0,
    "wypadki_lekkie": 0,
    "wskaznik_wypadkowosci": "opis lub null"
  }},
  "pracownicy": {{
    "szkolenia_godziny": 0,
    "liczba_przeszkolonych": 0
  }},
  "roznorodnosc": {{
    "kobiety_procent": 0,
    "zarzad_kobiety_procent": 0
  }},
  "spolecznosc": {{
    "wolontariat_akcje": 0,
    "skargi_od_mieszkancow": 0
  }},
  "podsumowanie": "Krótki opis sytuacji socjalnej."
}}
"""

    try:
        # 4. Wywołanie OpenAI
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Jesteś analitykiem ESG. Zwracaj tylko czysty JSON."},
                {"role": "user", "content": social_prompt}
            ],
            response_format={"type": "json_object"}  # Wymuszenie formatu JSON
        )

        analysis_result = response.choices[0].message.content

        # 5. Zapis do bazy
        save_report(
            user_id=1,
            input_text=f"[Social REAL] {report_path}",
            response_text=analysis_result,
            report_type="social_analysis"
        )

        return {
            "status": "success",
            "data": analysis_result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")


@app.post("/analyze-environmental")
async def analyze_environmental(
    report_path: str,
    user = Depends(get_current_user)
):
    """
    PRODUKCYJNY ENDPOINT ENVIRONMENTAL (E).
    Wymaga klucza OpenAI API. Analizuje twarde dane liczbowe (CO2, woda, energia).
    """
    # 1. Konfiguracja
    openai_client = get_openai_client()
    if openai_client is None:
        raise HTTPException(
            status_code=500,
            detail="OpenAI API key is missing. Configure .env file."
        )

    # 2. Walidacja plików
    report_dir = Path(report_path)
    if not report_dir.exists():
        raise HTTPException(status_code=404, detail=f"Directory not found: {report_path}")

    text_file = report_dir / "text.txt"
    if not text_file.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {text_file}")

    full_text = text_file.read_text(encoding="utf-8")

    # 3. Prompt Systemowy (Environmental)
    env_prompt = f"""Przeanalizuj poniższy tekst dokumentacji i wyciągnij twarde dane ŚRODOWISKOWE (E).
Zwróć szczególną uwagę na jednostki (kWh, tCO2e, Mg, m3).

DANE WEJŚCIOWE:
{full_text[:50000]}

OCZEKIWANY FORMAT JSON:
{{
  "kategoria": "Environmental",
  "emisje_co2": {{
    "scope_1_wartosc": null,
    "scope_2_wartosc": null,
    "scope_3_wartosc": null,
    "jednostka": "tCO2e"
  }},
  "energia": {{
    "zuzycie_calkowite": null,
    "jednostka": "kWh",
    "oze_procent": null
  }},
  "woda": {{
    "zuzycie": null,
    "jednostka": "m3"
  }},
  "odpady": {{
    "masa_calkowita": null,
    "jednostka": "Mg",
    "recykling_procent": null
  }},
  "certyfikaty": ["lista znalezionych certyfikatów np. BREEAM"],
  "podsumowanie": "Krótka ocena wpływu na środowisko."
}}
"""

    try:
        # 4. Wywołanie OpenAI
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Jesteś inżynierem środowiska. Zwracaj tylko czysty JSON."},
                {"role": "user", "content": env_prompt}
            ],
            response_format={"type": "json_object"}
        )

        analysis_result = response.choices[0].message.content

        # 5. Zapis do bazy
        save_report(
            user_id=1,
            input_text=f"[Environmental REAL] {report_path}",
            response_text=analysis_result,
            report_type="environmental_analysis"
        )

        return {
            "status": "success",
            "data": analysis_result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

@app.post("/analyze-governance")
async def analyze_governance(
    report_path: str,
    user = Depends(get_current_user)
):
    """
    PRODUKCYJNY ENDPOINT GOVERNANCE (G).
    Wymaga klucza OpenAI API. Analizuje dokumenty pod kątem ładu korporacyjnego.
    """
    # 1. Konfiguracja klienta OpenAI
    openai_client = get_openai_client()
    if openai_client is None:
        raise HTTPException(
            status_code=500,
            detail="OpenAI API key is missing. Configure .env file."
        )

    # 2. Walidacja ścieżki
    report_dir = Path(report_path)
    if not report_dir.exists():
        raise HTTPException(status_code=404, detail=f"Directory not found: {report_path}")

    text_file = report_dir / "text.txt"
    if not text_file.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {text_file}")

    full_text = text_file.read_text(encoding="utf-8")

    # 3. Prompt systemowy Governance
    gov_prompt = f"""Przeanalizuj poniższy tekst i wyciągnij informacje dotyczące kategorii GOVERNANCE (G).
Skup się na strukturze zarządczej, etyce, ryzykach, politykach wewnętrznych oraz zgodności z przepisami.

DANE WEJŚCIOWE:
{full_text[:50000]}

INSTRUKCJA:
Zwróć dane w formacie JSON. Jeśli informacji brakuje, wstaw null.
Koncentruj się na danych, a nie na interpretacjach.

OCZEKIWANY FORMAT JSON:
{{
  "kategoria": "Governance",
  "struktura_zarzadzania": {{
    "liczba_czlonkow_zarzadu": null,
    "komitety": ["np. komitet audytu, komitet ds. ryzyka"],
    "niezalezni_czlonkowie_procent": null
  }},
  "polityki": {{
    "polityka_antykorupcyjna": null,
    "kodeks_etyki": null,
    "polityka_zakupowa": null,
    "polityka_whistleblowing": null
  }},
  "ryzyka_i_kontrola": {{
    "zidentyfikowane_ryzyka": ["lista ryzyk"],
    "system_kontroli_wewnetrznej": null,
    "procedury_nadzoru_nad_podwykonawcami": null
  }},
  "zgodnosc": {{
    "naruszenia_prawne": null,
    "kary_finansowe": null,
    "certyfikaty_zarzadcze": ["np. ISO 37001"]
  }},
  "transparentnosc": {{
    "raportowanie_esg": null,
    "ujawnienia_finansowe": null,
    "polityka_komunikacji": null
  }},
  "podsumowanie": "Krótka ocena ładu korporacyjnego."
}}
"""

    try:
        # 4. Wywołanie OpenAI
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Jesteś ekspertem ds. ładu korporacyjnego. Zwracaj tylko czysty JSON."},
                {"role": "user", "content": gov_prompt}
            ],
            response_format={"type": "json_object"}
        )

        analysis_result = response.choices[0].message.content

        # 5. Zapis do bazy
        save_report(
            user_id=1,
            input_text=f"[Governance REAL] {report_path}",
            response_text=analysis_result,
            report_type="governance_analysis"
        )

        return {
            "status": "success",
            "data": analysis_result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

# ======= ENDPOINT BAZY WIEDZY ========
# Importujemy serwis (upewnij się, że ścieżka importu jest poprawna dla twojej struktury folderów)
try:
    from backend.services.knowledge_service import add_document_to_knowledge_base
except ImportError:
    from database.knowledge_service import add_document_to_knowledge_base

# Model wejściowy - dopasowany do tabeli knowledge_documents
class KnowledgeInput(BaseModel):
    title: str
    source: str         # np. nazwa pliku lub URL
    raw_text: str       # To trafi do kolumny 'raw_text'
    tag: Optional[str] = "general" # Domyślny tag, jeśli user nie poda

@app.post("/knowledge/add")
async def add_knowledge(
    item: KnowledgeInput,
    user = Depends(get_current_user) # zakomentuj jak chcesz testować, a nie masz pasów do autoryzacji (kłódka przy endpointcie w swaggerze)
):
    """
    Endpoint do zasilania bazy wiedzy.
    Przyjmuje dokument, zapisuje oryginał i tnie go na kawałki (chunks).
    """
    try:
        result = await add_document_to_knowledge_base(
            title=item.title,
            source=item.source,
            raw_text=item.raw_text,
            tag=item.tag
        )
        return {
            "status": "success",
            "message": "Dokument i chunki zostały zapisane w Supabase",
            "data": result
        }
    except Exception as e:
        print(f"Error adding knowledge: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/knowledge/upload")
async def upload_knowledge_files(
    files: List[UploadFile] = File(...),
    tag: str = Form("general"),
    document_type: str = Form("general"),
    version: str = Form("1.0"),
    user = Depends(get_current_user)
):
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

                db_res = add_document_to_knowledge_base(
                    title=safe_name,
                    source=f"upload:{safe_name}",
                    raw_text=raw_text,
                    tag=tag,
                    document_type=document_type,
                    version=version
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
    version: str = Form("1.0")
):
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
        version=version
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

# =============== TEST EMBEDDINGU ==============
# Importujemy nasz nowy serwis
try:
    from database.embedding_service import get_embedding
except ImportError:
    from database.embedding_service import get_embedding

# Model dla testu
class EmbeddingTestInput(BaseModel):
    text: str

@app.post("/test-embedding")
async def test_embedding_generation(item: EmbeddingTestInput):
    """
    Endpoint testowy (Task #2).
    Sprawdza, czy mamy połączenie z OpenAI i czy potrafimy wygenerować wektor.
    """
    vector = await get_embedding(item.text)

    return {
        "status": "success",
        "input_text_preview": item.text[:50] + "...",
        "vector_length": len(vector),  # Powinno być 1536 dla text-embedding-3-small
        "vector_preview": vector[:5]  # Pokażmy tylko 5 pierwszych liczb, żeby nie zapchać ekranu
    }
# ========= KONIEC TESTU EMBEDDINGU =========
