from dotenv import load_dotenv
import os
from pathlib import Path
import tempfile
import shutil
from openai import OpenAI
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .parsers.dispatcher import ParserDispatcher
from .parsers.output_writer import write_result

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

# pobiera klucz z pamięci środowiska
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
@app.get("/ping")
def ping():
    return {"message":"pong"}
@app.post("/upload")
async def upload_file(file:UploadFile= File(...)):
    contents = await file.read()
    return {"filename": file.filename}
    
# response = client.chat.completions.create(
#     model="gpt-4.1-nano",
#     messages=[
#         {"role": "system", "content": "Jesteś ekspertem ESG w branży budowlanej."},
#         {"role": "user", "content": "Podaj trzy przykłady działań proekologicznych na placu budowy."}
#     ]
# )
# print(response.choices[0].message.content)

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
