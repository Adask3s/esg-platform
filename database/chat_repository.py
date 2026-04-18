from database.supabase_client import get_supabase
import json

def create_chat_session(user_id: str, title: str = "Nowa konwersacja") -> str:
    supabase = get_supabase()
    response = supabase.table("chat_sessions").insert({
        "user_id": user_id,
        "title": title
    }).execute()
    if not response.data:
        raise Exception("Nie udało się utworzyć sesji czatu")
    return response.data[0]["id"]

def get_chat_sessions(user_id: str, limit: int = 50, offset: int = 0):
    supabase = get_supabase()
    response = supabase.table("chat_sessions") \
        .select("*") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .range(offset, offset + limit - 1) \
        .execute()
    return response.data

def get_chat_messages(session_id: str, limit: int = 50, offset: int = 0):
    supabase = get_supabase()
    response = supabase.table("chat_messages") \
        .select("*") \
        .eq("session_id", session_id) \
        .order("created_at", desc=False) \
        .range(offset, offset + limit - 1) \
        .execute()
    return response.data

def add_chat_message(session_id: str, role: str, content: str, rag_used: bool = False, applied_filter: str = None, used_chunks: str = None) -> str:
    supabase = get_supabase()
    payload = {
        "session_id": session_id,
        "role": role,
        "content": content,
    }
    if role == "assistant":
        payload["rag_used"] = rag_used
        payload["applied_filter"] = applied_filter
        payload["used_chunks"] = used_chunks
        
    response = supabase.table("chat_messages").insert(payload).execute()
    if not response.data:
        raise Exception("Nie udało się zapisać wiadomości czatu")
    return response.data[0]["id"]
