import asyncio
import os
import sys
from dotenv import load_dotenv

# Wczytanie zmiennych środowiskowych z pliku .env (klucze Supabase i OpenAI)
load_dotenv()

# Import funkcji RAG z backendu
from backend.RAG.rag_retriever import retrieve_context_async

async def run_diagnostics(query: str, user_id: str, tag: str = None, limit: int = 20, threshold: float = 0.20):
    print("=" * 60)
    print("URUCHAMIANIE DIAGNOSTYKI RAG...")
    print(f"Pytanie: '{query}'")
    print(f"User ID: {user_id}")
    print(f"Filtr tagu: {tag}")
    print(f"Limit wyników: {limit}, Próg podobieństwa: {threshold}")
    print("=" * 60)

    try:
        # Bezpośrednie uderzenie w funkcję, z pominięciem FastAPI i Celery
        results = await retrieve_context_async(
            query=query,
            user_id=user_id,
            match_count=limit,
            match_threshold=threshold,
            filter_tag=tag
        )

        if not results:
            print("\nBLAD ❌ WYNIK: Baza nie zwróciła absolutnie żadnych dokumentów.")
            print("Możliwe przyczyny:")
            print("1. Dokumenty nie należą do tego user_id.")
            print("2. Użyto tagu, którego nie ma w bazie.")
            print("3. Próg podobieństwa (threshold) jest zbyt rygorystyczny.")
            return

        print(f"\nDZIALA ✅ WYNIK: Znaleziono {len(results)} pasujących fragmentów (chunków).\n")

        # Analiza koszyków (Zbiór 1 (dokumenty użytkownika) vs Zbiór 2 (baza wiedzy modelu))
        user_docs = set()
        kb_docs = set()

        for idx, chunk in enumerate(results, 1):
            # Wyciągnięcie podziału linii poza f-stringa
            lines = chunk.split('\n')
            first_line = lines[0] if len(lines) > 0 else "Brak_nagłówka"

            if "celex" in first_line.lower() or "rozporządzenie" in first_line.lower():
                kb_docs.add(first_line)
            else:
                user_docs.add(first_line)

            print(f"--- Chunk {idx} ---")
            print(f"Nagłówek: {first_line}")

            # Bezpieczne pobranie drugiej linii (jeśli istnieje)
            snippet = lines[1][:100] if len(lines) > 1 else "Brak treści..."
            print(f"Początek tekstu: {snippet}...\n")

        print("=" * 60)
        print("PODSUMOWANIE ŹRÓDEŁ:")
        print(f"Dokumenty Firmowe: {user_docs if user_docs else 'Brak'}")
        print(f"Dokumenty Unijne: {kb_docs if kb_docs else 'Brak'}")
        print("=" * 60)

    except Exception as e:
        print(f"\nBLAD ❌ BŁĄD KRYTYCZNY: {e}")


if __name__ == "__main__":
    # Oczekujemy argumentów z konsoli: python diagnose_rag.py "Pytanie" "uuid-uzytkownika" ["Tag"]
    if len(sys.argv) < 3:
        print("Użycie: python diagnose_rag.py \"Twoje pytanie\" \"user_id\" [\"Opcjonalny_Tag\"]")
        sys.exit(1)

    test_query = sys.argv[1]
    test_user_id = sys.argv[2]
    test_tag = sys.argv[3] if len(sys.argv) > 3 else None

    asyncio.run(run_diagnostics(test_query, test_user_id, test_tag))