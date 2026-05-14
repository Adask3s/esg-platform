import requests
import sys
import time

# Konfiguracja
BASE_URL = "http://127.0.0.1:8000"
TEST_TAG = sys.argv[1] if len(sys.argv) > 1 else "Environmental"


def print_step(step_num, message):
    print(f"\n[KROK {step_num}] {message}...")


def print_success(message):
    print(f"  SUKCES: {message}")


def fail_test(stage, reason, details=""):
    print(f"\n  BLAD KRYTYCZNY NA ETAPIE: {stage}")
    print(f"  Przyczyna: {reason}")
    if details:
        print(f"  Szczegóły serwera: {details}")
    sys.exit(1)


def wait_for_task(task_id, headers, expected_filename=None, timeout_seconds=300, poll_seconds=2):
    status_url = f"{BASE_URL}/status/{task_id}"
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        response = requests.get(status_url, headers=headers, timeout=30)
        if response.status_code != 200:
            fail_test("Status", f"Serwer zwrocil kod bledu {response.status_code}", response.text)

        payload = response.json()
        state = payload.get("state")
        progress = payload.get("progress")
        stage_pl = payload.get("stage_pl")
        print(f"  status={state}, progress={progress}, etap={stage_pl}")

        if expected_filename and payload.get("filename") and payload.get("filename") != expected_filename:
            fail_test("Status", "Zwrocono nieoczekiwana nazwe pliku.", payload)

        if state == "SUCCESS":
            return payload

        if state == "FAILURE":
            fail_test("Celery", "Task zakończył się błędem.", payload)

        time.sleep(poll_seconds)

    fail_test("Celery", f"Task nie zakonczyl sie w ciagu {timeout_seconds} sekund.")


def run_e2e_test():
    print("=== ROZPOCZECIE TESTU INTEGRACYJNEGO E2E ===")

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
        fail_test("Autoryzacja", f"Nie udalo sie zalogowac. Kod bledu: {auth_response.status_code}", auth_response.text)

    token = auth_response.json().get("access_token")
    if not token:
        fail_test("Autoryzacja", "Serwer zwrocil kod 200, ale nie przekazal pola 'access_token'.", auth_response.json())

    print_success("Token JWT pobrany pomyslnie.")

    # Przygotowanie nagłówka z tokenem dla kolejnych endpointów
    headers = {
        "Authorization": f"Bearer {token}"
    }

    # ---------------------------------------------------------
    # KROK 1: ASYNC CELERY TASK — REPORT GENERATION
    # ---------------------------------------------------------
    print_step(1, f"Uruchamianie taska /report/generate dla scope '{TEST_TAG}'")

    report_url = f"{BASE_URL}/report/generate"
    try:
        response = requests.post(report_url, headers=headers, json={"report_scope": TEST_TAG}, timeout=30)
    except requests.exceptions.ConnectionError:
        fail_test("Raport", "Nie mozna polaczyc sie z serwerem. Czy Uvicorn jest uruchomiony?")

    if response.status_code != 200:
        fail_test("Raport", f"Serwer zwrocil kod bledu {response.status_code}", response.text)

    res_json = response.json()
    task_id = res_json.get("task_id")
    if not task_id:
        fail_test("Raport", "Serwer nie zwrocil task_id.", res_json)

    print_success(f"Task raportu w kolejce: {task_id}")

    status_json = wait_for_task(task_id, headers)
    result = status_json.get("result") or {}
    if not isinstance(result, dict):
        fail_test("Celery", "Wynik taska ma nieoczekiwany format.", status_json)

    if result.get("status") != "success":
        fail_test("Raport", "Task zakonczyl sie, ale nie zwrocil statusu success.", status_json)

    data = result.get("data") or {}
    if not isinstance(data, dict):
        fail_test("Raport", "Pole data ma nieoczekiwany format.", status_json)

    if not data.get("wskazniki_liczbowe"):
        fail_test("Raport", "Raport nie zawiera wskaznikow liczbowych.", status_json)

    if not data.get("wdrozone_polityki_i_dzialania"):
        fail_test("Raport", "Raport nie zawiera listy polityk i dzialan.", status_json)

    print_success("Task Celery zakonczony poprawnie i zwrocil pelny raport ESG.")
    print_success(f"Liczba wskaznikow: {len(data.get('wskazniki_liczbowe', []))}")

    print("\n=== PODSUMOWANIE ===")
    print("Test E2E przeszedl w 100% pomyslnie. Celery wygenerowal raport i status zakonczyl sie SUCCESS.")


if __name__ == "__main__":
    run_e2e_test()