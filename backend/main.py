from dotenv import load_dotenv
import os
from pathlib import Path
import tempfile
import shutil
from openai import OpenAI
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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