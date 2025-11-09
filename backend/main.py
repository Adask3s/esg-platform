from dotenv import load_dotenv
import os
from pathlib import Path
import tempfile
import shutil
from openai import OpenAI
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from typing import List
from fastapi.middleware.cors import CORSMiddleware
from database.report_repo import save_report

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
    if client is None:
        client = get_openai_client()
    
    if client is None:
        return {
            "status": "error",
            "message": "Brak klucza OPENAI_API_KEY",
            "help": "Dodaj OPENAI_API_KEY do pliku .env lub ustaw zmienną środowiskową"
        }
    return {
        "status": "ok",
        "message": "Klient OpenAI zainicjalizowany"
    }

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    contents = await file.read()
    return {"filename": file.filename}

# ============ LOGIKA STATUSU ZADAŃ =============
task_status = {}  # dict: id -> "in_progress" / "completed" / "error"
task_counter = 0  # tylko do tworzenia unikalnych ID

def run_parsing(file_path: Path, task_id: int):
    """Działa w tle, wykonuje parse_upload."""
    global task_status
    try:
        dispatcher = ParserDispatcher()
        result = dispatcher.parse(file_path)
        project_root = Path(__file__).resolve().parents[1]
        out_root = project_root / "output_test_parser"
        write_result(result, out_root)
        # zapis do bazy
        save_report(
            user_id=1,                                     # tymczasowo „1”, potem dynamicznie
            input_text=str(file_path.name),                # nazwa lub ścieżka pliku
            response_text="Plik przetworzony pomyślnie",   # można potem dodać wynik OpenAI
            report_type="parse_result"
        )
        task_status[task_id] = "completed"
    except Exception as e:
        task_status[task_id] = f"error: {e}"
    finally:
        try:
            shutil.rmtree(file_path.parent, ignore_errors=True)
        except Exception:
            pass


@app.post("/process")
async def process_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Startuje parsowanie w tle i zwraca task_id."""
    global task_counter
    task_counter += 1
    task_id = task_counter
    task_status[task_id] = "in_progress"

    tmp_dir = tempfile.mkdtemp(prefix=f"task_{task_id}_")
    tmp_path = Path(tmp_dir) / file.filename
    tmp_path.write_bytes(await file.read())

    background_tasks.add_task(run_parsing, tmp_path, task_id)
    return {"task_id": task_id, "status": "in_progress"}


@app.get("/status/{task_id}")
def get_status(task_id: int):
    """Zwraca status bieżącego zadania."""
    status = task_status.get(task_id)
    if not status:
        return {"task_id": task_id, "status": "not_found"}
    return {"task_id": task_id, "status": status}