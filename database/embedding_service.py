import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# Pobieramy klucz API
api_key = os.environ.get("OPENAI_API_KEY")

if not api_key:
    # To tylko ostrzeżenie, żeby nie wywaliło apki przy starcie,
    # ale przy próbie użycia rzuci błędem
    print("WARNING: Brak OPENAI_API_KEY w pliku .env")

# Klient asynchroniczny (dla FastAPI)
aclient = AsyncOpenAI(api_key=api_key)

async def get_embedding(text: str) -> list[float]:
    """
    Zamienia tekst na wektor (listę liczb) używając modelu OpenAI.
    Używamy modelu 'text-embedding-3-small', bo do tego używa się innych modeli niż
    do czatowania (ten ma najlepszy stosunek cena/jakość).
    """
    if not text:
        return []

    # Zamiana znaków nowej linii na spacje to dobra praktyka przy embeddingach
    text = text.replace("\n", " ")

    try:
        response = await aclient.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        # Zwracamy samą listę liczb (vector)
        return response.data[0].embedding
    except Exception as e:
        print(f"Błąd generowania embeddingu: {e}")
        # W zależności od strategii, możemy rzucić błąd dalej lub zwrócić pustą listę
        raise e