from dotenv import load_dotenv
import os
from pathlib import Path
import tempfile
import shutil
from openai import OpenAI
from fastapi import FastAPI, UploadFile, File, HTTPException
from typing import List
from fastapi.middleware.cors import CORSMiddleware
from database.report_repo import save_report
from .utils.files import save_upload_streamed, sanitize_filename, validate_file_on_disk

# Celery imports (support both package and script-run modes)
try:
    from backend.celery.celery_app import celery_app
    from backend.celery.tasks import parse_and_store
except ImportError:
    from backend.celery.celery_app import celery_app  # type: ignore
    from backend.celery.tasks import parse_and_store  # type: ignore
from celery.result import AsyncResult

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

# wczytuje dane z pliku .env
load_dotenv()

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
async def process_file(file: UploadFile = File(...)):
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
def get_status(task_id: str):
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

@app.post("/analyze-social")
async def analyze_social(report_path: str, use_mock: bool = False):
    """
    Analizuje dane społeczne (Social - S) z już sparsowanego raportu ESG.
    Wysyła dane do OpenAI z promptem specyficznym dla aspektów społecznych.

    Args:
        report_path: Ścieżka do katalogu z sparsowanym raportem (np. output_test_parser/raport__20251203_120000)
        use_mock: Jeśli True, zwraca mock-ową odpowiedź bez wywoływania OpenAI (do testów)

    Returns:
        Analiza LLM danych społecznych + zapis do bazy
    """
    # Inicjalizacja klienta OpenAI (pomiń jeśli mock)
    openai_client = None
    if not use_mock:
        openai_client = get_openai_client()
        if openai_client is None:
            raise HTTPException(
                status_code=500,
                detail="OpenAI API key not configured. Use ?use_mock=true for testing without API key."
            )

    # Walidacja ścieżki
    report_dir = Path(report_path)
    if not report_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Report directory not found: {report_path}"
        )

    # Wczytanie sparsowanego tekstu
    text_file = report_dir / "text.txt"
    if not text_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Text file not found in report: {text_file}"
        )

    try:
        full_text = text_file.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reading text file: {str(e)}"
        )

    # Prompt specyficzny dla analizy Social (S)
    social_prompt = f"""Jesteś ekspertem w analizie ESG, specjalizującym się w aspektach społecznych (Social).

Przeanalizuj poniższy raport i wyodrębnij TYLKO informacje dotyczące obszaru społecznego (S):

OBSZARY DO ANALIZY:
1. Bezpieczeństwo i higiena pracy (BHP)
2. Szkolenia i rozwój pracowników
3. Różnorodność i inkluzywność (gender diversity)
4. Programy wolontariatu i zaangażowanie społeczne
5. Wypadki przy pracy
6. Relacje ze społecznościami lokalnymi
7. Warunki pracy
8. Prawa pracownicze

RAPORT ESG:
{full_text}

ZADANIE:
Wyodrębnij i przedstaw w strukturalny sposób wszystkie dane dotyczące aspektów społecznych.
Jeśli raport zawiera konkretne liczby/wskaźniki, uwzględnij je w analizie.

Format odpowiedzi (JSON):
{{
  "kategoria": "Social",
  "kluczowe_wskazniki": [
    {{"nazwa": "...", "wartosc": "...", "jednostka": "..."}}
  ],
  "dzialania": ["..."],
  "wypadki_bhp": {{"liczba": ..., "opis": "..."}},
  "szkolenia": {{"liczba_pracownikow": ..., "procent_kobiet": ..., "tematyka": "..."}},
  "wolontariat": {{"liczba_programow": ..., "opis": "..."}},
  "podsumowanie": "..."
}}
"""

    try:
        # MOCK MODE - zwróć przykładową analizę bez wywoływania OpenAI
        if use_mock:
            llm_analysis = """{
  "kategoria": "Social",
  "kluczowe_wskazniki": [
    {"nazwa": "Przeszkoleni pracownicy", "wartosc": "400", "jednostka": "osoby"},
    {"nazwa": "Udział kobiet w szkoleniach", "wartosc": "35", "jednostka": "%"},
    {"nazwa": "Programy wolontariatu", "wartosc": "3", "jednostka": "programy"}
  ],
  "dzialania": [
    "Szkolenia z BHP i zrównoważonego budownictwa",
    "Programy wolontariatu pracowniczego",
    "Działania na rzecz różnorodności"
  ],
  "wypadki_bhp": {
    "liczba": 1,
    "opis": "1 lekkie zdarzenie wypadkowe bez hospitalizacji"
  },
  "szkolenia": {
    "liczba_pracownikow": 400,
    "procent_kobiet": 35,
    "tematyka": "BHP i zrównoważone budownictwo"
  },
  "wolontariat": {
    "liczba_programow": 3,
    "opis": "Realizacja 3 programów wolontariatu pracowniczego"
  },
  "podsumowanie": "Spółka aktywnie rozwija kompetencje pracowników w obszarze zrównoważonego rozwoju. Szczególny nacisk położono na bezpieczeństwo pracy (1 lekkie zdarzenie) oraz rozwój kompetencji (400 przeszkolonych pracowników). Pozytywnie ocenia się programy wolontariatu pracowniczego oraz działania na rzecz różnorodności."
}"""

            # Zapis do bazy danych
            try:
                report_id = save_report(
                    user_id=1,
                    input_text=f"[Social Analysis - MOCK] {report_path}",
                    response_text=llm_analysis,
                    report_type="social_analysis_mock"
                )
            except Exception as db_err:
                report_id = None
                print(f"⚠️  Warning: Could not save to database: {db_err}")

            return {
                "status": "success",
                "esg_category": "Social",
                "report_path": str(report_path),
                "report_id": report_id,
                "analysis": llm_analysis,
                "tokens_used": 0,
                "model": "mock-model (testing mode)",
                "is_mock": True
            }

        # REAL MODE - wywołanie OpenAI API
        # Wywołanie OpenAI API
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",  # Możesz zmienić na gpt-4 lub gpt-3.5-turbo
            messages=[
                {"role": "system", "content": "Jesteś ekspertem w analizie ESG ze specjalizacją w aspektach społecznych."},
                {"role": "user", "content": social_prompt}
            ],
            temperature=0.3,  # Niska temperatura dla bardziej faktycznej analizy
            max_tokens=2000
        )

        llm_analysis = response.choices[0].message.content

        # Zapis do bazy danych
        try:
            report_id = save_report(
                user_id=1,
                input_text=f"[Social Analysis] {report_path}",
                response_text=llm_analysis,
                report_type="social_analysis"
            )
        except Exception as db_err:
            # Nie blokuj odpowiedzi jeśli DB nie działa
            report_id = None
            print(f"⚠️  Warning: Could not save to database: {db_err}")

        return {
            "status": "success",
            "esg_category": "Social",
            "report_path": str(report_path),
            "report_id": report_id,
            "analysis": llm_analysis,
            "tokens_used": response.usage.total_tokens,
            "model": response.model
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"OpenAI API error: {str(e)}"
        )
