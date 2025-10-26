from dotenv import load_dotenv
import os
from openai import OpenAI

# wczytuje dane z pliku .env
load_dotenv()

# pobiera klucz z pamięci środowiska
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

response = client.chat.completions.create(
    model="gpt-4.1-nano",
    messages=[
        {"role": "system", "content": "Jesteś ekspertem ESG w branży budowlanej."},
        {"role": "user", "content": "Podaj trzy przykłady działań proekologicznych na placu budowy."}
    ]
)
print(response.choices[0].message.content)