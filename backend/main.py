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