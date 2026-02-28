import requests
import sys
import os

# Konfiguracja
BASE_URL = "http://127.0.0.1:8000"
# Podaj dokładną ścieżkę do swojego pliku PDF
PDF_PATH = "RAPORT-ZRÓWNOWAŻONEGO-ROZWOJU-_ESG_.pdf"
TEST_TAG = "Environmental"


def print_step(step_num, message):
    print(f"\n[KROK {step_num}] {message}...")


def print_success(message):
    print(f"  ✅ SUKCES: {message}")


def fail_test(stage, reason, details=""):
    print(f"\n  ❌ BŁĄD KRYTYCZNY NA ETAPIE: {stage}")
    print(f"  Przyczyna: {reason}")
    if details:
        print(f"  Szczegóły serwera: {details}")
    sys.exit(1)


def run_e2e_test():
    print("=== ROZPOCZĘCIE TESTU INTEGRACYJNEGO E2E ===")

    if not os.path.exists(PDF_PATH):
        fail_test("Przygotowanie", f"Nie znaleziono pliku PDF pod ścieżką: {PDF_PATH}")

    # ---------------------------------------------------------
    # KROK 0: LOGOWANIE I POBRANIE TOKENA JWT
    # ---------------------------------------------------------
    print_step(0, "Logowanie do systemu (admin/admin)")

    auth_url = f"{BASE_URL}/auth/login"

    # Dane zgodne z OAuth2PasswordRequestForm
    auth_data = {
        "grant_type": "password",
        "username": "admin",
        "password": "admin",
        "scope": "",
        "client_id": "string",
        "client_secret": "string"
    }

    # Używamy data= zamiast json=, żeby wymusić application/x-www-form-urlencoded
    auth_response = requests.post(auth_url, data=auth_data)

    if auth_response.status_code != 200:
        fail_test("Autoryzacja", f"Nie udało się zalogować. Kod błędu: {auth_response.status_code}", auth_response.text)

    token = auth_response.json().get("access_token")
    if not token:
        fail_test("Autoryzacja", "Serwer zwrócił kod 200, ale nie przekazał pola 'access_token'.", auth_response.json())

    print_success("Token JWT pobrany pomyślnie.")

    # Przygotowanie nagłówka z tokenem dla kolejnych endpointów
    headers = {
        "Authorization": f"Bearer {token}"
    }

    # ---------------------------------------------------------
    # KROK 1: UPLOAD & EMBEDDING
    # ---------------------------------------------------------
    print_step(1, f"Wysyłanie pliku '{PDF_PATH}' z tagiem '{TEST_TAG}'")

    upload_url = f"{BASE_URL}/user/documents/upload"
    try:
        with open(PDF_PATH, 'rb') as f:
            files = {'file': (os.path.basename(PDF_PATH), f, 'application/pdf')}
            data = {'tag': TEST_TAG}

            # WSTRZYKUJEMY NAGŁÓWEK AUTORYZACYJNY TUTAJ!
            response = requests.post(upload_url, headers=headers, files=files, data=data)
    except requests.exceptions.ConnectionError:
        fail_test("Upload", "Nie można połączyć się z serwerem. Czy Uvicorn jest uruchomiony?")

    if response.status_code != 200:
        fail_test("Upload", f"Serwer zwrócił kod błędu {response.status_code}", response.text)

    res_json = response.json()

    if res_json.get("status") != "success":
        fail_test("Upload", "Status w JSON nie jest 'success'", res_json)

    details = res_json.get("details", {})
    chunks_processed = details.get("chunks_processed", 0)
    if chunks_processed == 0:
        fail_test("Chunkowanie", "Serwer zwrócił 0 przetworzonych chunków. Plik może być pusty.", res_json)

    print_success(f"Plik wgrany poprawnie. Utworzono chunków: {chunks_processed}.")

    # ---------------------------------------------------------
    # KROK 2: RETRIEVAL & PROMPT GENERATION (CHAT/ASK)
    # ---------------------------------------------------------
    print_step(2, "Wysyłanie zapytania RAG (Test Context Injection)")

    ask_url = f"{BASE_URL}/chat/ask"
    payload = {
        "query": None,
        "tag": TEST_TAG
    }

    # Zostawiam tu nagłówek profilaktycznie, gdybyście dodali Depends() do /chat/ask
    response = requests.post(ask_url, headers=headers, json=payload)

    if response.status_code != 200:
        fail_test("Retrieval/Ask", f"Serwer zwrócił kod błędu {response.status_code}", response.text)

    ask_json = response.json()

    # ---------------------------------------------------------
    # KROK 3: WERYFIKACJA LOGIKI I ODPOWIEDZI AI
    # ---------------------------------------------------------
    print_step(3, "Weryfikacja jakości wygenerowanego promptu i odpowiedzi AI")

    debug_prompt = ask_json.get("debug_prompt", "")
    ai_answer = ask_json.get("ai_answer", "")

    if "UWAGA: Skup się w swojej analizie wyłącznie na aspekcie" not in debug_prompt:
        fail_test("Prompt Builder", "Brak kluczowej instrukcji skupienia się na Tagu w wygenerowanym prompcie.")

    if "Brak pasujących fragmentów w bazie danych" in debug_prompt:
        fail_test("Wyszukiwanie SQL",
                  "Baza nie znalazła chunków. Sprawdź parametry Threshold, tagi w bazie lub funkcję SQL.")

    if not ai_answer or len(ai_answer.strip()) < 50:
        fail_test("Odpowiedź AI", "Odpowiedź od OpenAI jest pusta lub podejrzanie krótka.", ask_json)

    print_success("Prompt został zbudowany prawidłowo.")
    print_success("OpenAI zwróciło poprawny, wygenerowany raport.")

    print("\n=== PODSUMOWANIE ===")
    print("Test E2E przeszedł w 100% pomyślnie. Pipeline działa stabilnie.")


if __name__ == "__main__":
    run_e2e_test()