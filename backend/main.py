from dotenv import load_dotenv
import os
from pathlib import Path
import tempfile
import shutil
from openai import OpenAI
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
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

@app.post("/parse")
async def parse_upload(file: UploadFile = File(...)):
    """Upload a file, parse it server-side, and write results into output_test_parser/.
    Returns a manifest with output paths so a dev can inspect artifacts locally.
    """
    # Save to a temporary file first
    tmp_dir = tempfile.mkdtemp(prefix="upload_")
    tmp_path = Path(tmp_dir) / file.filename
    try:
        data = await file.read()
        tmp_path.write_bytes(data)
        
        dispatcher = ParserDispatcher()
        result = dispatcher.parse(tmp_path)
        
        project_root = Path(__file__).resolve().parents[1]
        out_root = project_root / "output_test_parser"
        manifest = write_result(result, out_root)
        return {"status": "ok", "manifest": manifest}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # cleanup temp files
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

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