import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise ValueError("Brak zmiennych SUPABASE_URL lub SUPABASE_KEY w pliku .env")

supabase: Client = create_client(url, key)

def get_supabase() -> Client:
    return supabase