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

# ---------------------------------------------------------
# REAL ENDPOINTS (NO MOCKS)
# ---------------------------------------------------------

@app.post("/analyze-social")
async def analyze_social(report_path: str):
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
async def analyze_environmental(report_path: str):
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
