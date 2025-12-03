"""
PRAWDZIWY TEST - czy klucz OpenAI działa
"""
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")

print("=" * 60)
print("TEST KLUCZA OPENAI API")
print("=" * 60)
print(f"Klucz (pierwsze 20 znaków): {api_key[:20]}...")
print(f"Klucz (ostatnie 4 znaki): ...{api_key[-4:]}")
print(f"Długość: {len(api_key)}")
print(f"Zaczyna się od 'sk-': {api_key.startswith('sk-')}")
print("-" * 60)

try:
    print("🔄 Tworzenie klienta OpenAI...")
    client = OpenAI(api_key=api_key)
    print("✅ Klient utworzony")
    
    print("\n🔄 Test request: models.list()...")
    models = client.models.list()
    first_model = next(iter(models), None)
    print(f"✅ DZIAŁA! Otrzymano model: {first_model.id if first_model else 'brak modeli'}")

    print("\n🔄 Test request: chat completion...")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Say 'test OK' if you receive this"}],
        max_tokens=10
    )
    print(f"✅ DZIAŁA! GPT odpowiedział: {response.choices[0].message.content}")
    
    print("\n" + "=" * 60)
    print("✅ KLUCZ API JEST W PEŁNI FUNKCJONALNY!")
    print("=" * 60)
    
except Exception as e:
    print(f"\n❌ BŁĄD: {e}")
    print("\n" + "=" * 60)
    print("❌ KLUCZ API NIE DZIAŁA!")
    print("=" * 60)
    print("\nCo zrobić:")
    print("1. Wejdź na: https://platform.openai.com/api-keys")
    print("2. Sprawdź czy klucz nie wygasł")
    print("3. Wygeneruj nowy klucz")
    print("4. Zaktualizuj .env: OPENAI_API_KEY=nowy_klucz")

