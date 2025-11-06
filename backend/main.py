from dotenv import load_dotenv
import os
from openai import OpenAI
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

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

# Pomocnicza funkcja do inicjalizacji klienta
def init_openai():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("WARNING: OPENAI_API_KEY nie jest ustawiony!")
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception as e:
        print(f"ERROR: Nie można utworzyć klienta OpenAI: {e}")
        return None

# Leniwa inicjalizacja - klient zostanie utworzony tylko gdy będzie potrzebny
client = None

@app.get("/ping")
def ping():
    return {"message": "pong"}

@app.get("/openai-status")
def openai_status():
    global client
    if client is None:
        client = init_openai()
    
    if client is None:
        return {
            "status": "error",
            "message": "Brak klucza OPENAI_API_KEY"
        }
    return {
        "status": "ok",
        "message": "Klient OpenAI zainicjalizowany"
    }

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    contents = await file.read()
    return {"filename": file.filename}