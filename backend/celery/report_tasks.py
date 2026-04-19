"""
Celery task dla /report/generate.

Generowanie raportu ESG JSON: retrieve_context -> prompt -> OpenAI -> save_report.
Endpoint HTTP zwraca tylko task_id; klient pobiera wynik przez GET /status/{task_id}.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

import openai
from openai import OpenAI

from backend.celery.celery_app import celery_app

# Transient errors — retryowalne
TRANSIENT_EXC = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    ConnectionError,
    TimeoutError,
)

# Słowa-klucze do RAG, per tag (lustrzane do main.py)
VECTOR_QUERIES = {
    "Environmental": "emisje CO2, tCO2e, zużycie energii, MWh, megawatogodziny, recykling, woda, ślad węglowy, panele fotowoltaiczne, odpady",
    "Social": "liczba pracowników, szkolenia, kobiety, mężczyźni, wypadki, BHP, bezpieczeństwo, rotacja, wolontariat, społeczność",
    "Governance": "zarząd, audyty, korupcja, whistleblowing, kary finansowe, rada nadzorcza, etyka, polityka, zgodność compliance",
    "ESG": "emisje tCO2e, zużycie energii MWh, recykling, liczba pracowników, szkolenia BHP, zarząd, audyty, kary finansowe, whistleblowing",
}

TAG_HINTS = {
    "Environmental": "Szukaj twardych danych o: emisjach gazów (Scope 1, 2, 3), zużyciu energii, wodzie, odpadach, recyklingu i śladzie węglowym.",
    "Social": "Szukaj twardych danych o: liczbie pracowników, udziale kobiet/mężczyzn, wypadkach przy pracy (BHP), rotacji kadr i godzinach szkoleń.",
    "Governance": "Szukaj twardych danych o: strukturze zarządu (niezależność), liczbie audytów, zgłoszeniach naruszeń (whistleblowing) i karach finansowych.",
    "ESG": "Szukaj kluczowych, twardych danych z każdego filaru: środowiska (np. emisje), społeczeństwa (np. pracownicy) i ładu korporacyjnego (np. audyty).",
}


def _build_report_prompt(target_tag: str, user_context: str, kb_context: str, hint: str) -> str:
    return f"""Jesteś bezlitosnym audytorem danych ESG. Twoim jedynym celem jest ekstrakcja TWARDYCH WYNIKÓW LICZBOWYCH konkretnej firmy dla obszaru: {target_tag}.

Masz przed sobą dwa całkowicie niezależne, fizycznie oddzielone zbiory danych:

=== ZBIÓR 1: DOKUMENTY FIRMY (TWOJE JEDYNE ŹRÓDŁO WSKAŹNIKÓW) ===
{user_context}

=== ZBIÓR 2: BAZA WIEDZY / PRAWO UE (TYLKO DO REFERENCJI PRAWNEJ) ===
{kb_context}

INSTRUKCJE KRYTYCZNE (ZŁAM JEDNĄ, A OBLEJESZ):
1. TWARDY PODZIAŁ ŹRÓDEŁ: Tablice "wskazniki_liczbowe", "wdrozone_polityki_i_dzialania" oraz "zidentyfikowane_ryzyka" MUSISZ wypełniać WYŁĄCZNIE danymi ze [ZBIORU 1] (Dokumenty Firmy).
2. ŚLEPOTA NA ZBIÓR 2: CAŁKOWICIE IGNORUJ wszelkie liczby, wskaźniki, żargon i przykłady ze [ZBIORU 2] przy wypełnianiu tablic. To jest tylko tło prawne. Służy Ci ono tylko do napisania sekcji "wnioski_i_zgodnosc_prawna".
3. ZAKAZ TWORZENIA PUSTYCH WSKAŹNIKÓW (BEZWZGLĘDNY): W tablicy "wskazniki_liczbowe" mogą znaleźć się TYLKO te wskaźniki, dla których w [ZBIORZE 1] występuje KONKRETNA LICZBA (np. 450, 850, 12%).
4. ZERO NULLI: Zabraniam używania wartości "null". Jeśli nie znasz dokładnej wartości ze ZBIORU 1, w ogóle nie dodawaj tego wskaźnika do JSON-a. Jeśli w ZBIORZE 1 nie ma twardych liczb, po prostu zostaw tablicę pustą [].
5. SPECJALIZACJA: {hint}

OCZEKIWANA, ŚCISŁA STRUKTURA JSON (Zastąp tagi <...> faktycznymi danymi z tekstu):
{{
  "kategoria": "{target_tag}",
  "wskazniki_liczbowe": [
     {{"nazwa": "<Krótka nazwa znalezionego wskaźnika>", "wartosc": <Tylko_liczba_bez_stringów>, "jednostka": "<np. tCO2e, %, MWh>"}}
  ],
  "wdrozone_polityki_i_dzialania": [
     "<Zidentyfikowane działanie firmy 1 ze ZBIORU 1>"
  ],
  "zidentyfikowane_ryzyka": [
     "<Zidentyfikowane ryzyko dla firmy ze ZBIORU 1>"
  ],
  "wnioski_i_zgodnosc_prawna": "<1-2 zdania oceniające wyniki firmy. Tutaj i TYLKO TUTAJ możesz odnieść się do tego, czy wyniki firmy ze ZBIORU 1 pasują do wymogów prawnych ze ZBIORU 2.>"
}}
"""


@celery_app.task(
    bind=True,
    name="backend.generate_report",
    autoretry_for=TRANSIENT_EXC,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=120,
    time_limit=180,
)
def generate_report_task(
    self,
    user_id: str,
    tag: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generuj raport ESG: RAG retrieval -> prompt -> OpenAI -> save_report.

    Zwraca JSON identyczny z tym, co poprzednio zwracał endpoint /report/generate.
    """
    # Lokalne importy — unikamy cykli przy starcie workera
    from backend.RAG.rag_retriever import retrieve_context_async
    from database.report_repo import save_report

    self.update_state(
        state="PROGRESS",
        meta={"step": "init", "stage_pl": "Inicjalizacja", "progress": 5, "user_id": user_id},
    )

    TAG_MAPPING = {
        "E": "Environmental",
        "S": "Social",
        "G": "Governance",
        "ESG": "ESG"
    }
    
    # Ustalenie kontekstu zapytania
    raw_tag = tag.strip() if tag and tag.strip() else "ESG"
    target_tag = TAG_MAPPING.get(raw_tag, raw_tag)
    
    # Usuwamy db_filter_tag, żeby sztucznie nie ucinało dokumentów wrzuconych np. z tagiem "project_x"
    db_filter_tag = None
    search_query = VECTOR_QUERIES.get(target_tag, VECTOR_QUERIES["ESG"])

    # === RAG retrieval ===
    self.update_state(
        state="PROGRESS",
        meta={"step": "retrieving_context", "stage_pl": "Wyszukiwanie kontekstu", "progress": 30, "tag": target_tag},
    )
    found_chunks = asyncio.run(retrieve_context_async(
        query=search_query,
        user_id=user_id,
        match_count=35,
        match_threshold=0.20,
        filter_tag=db_filter_tag,
    ))

    if not found_chunks:
        return {
            "status": "partial_success",
            "kategoria": target_tag,
            "message": "Brak danych w dokumentach źródłowych dla tego obszaru.",
            "data": None,
        }

    # === Budowa promptu (podział na zbiór prawny vs dane firmy) ===
    self.update_state(
        state="PROGRESS",
        meta={"step": "building_prompt", "stage_pl": "Budowanie promptu", "progress": 50, "tag": target_tag},
    )
    user_chunks = []
    kb_chunks = []
    for chunk in found_chunks:
        first_line = chunk.split('\n', 1)[0]
        if "CELEX" in first_line or "Rozporządzenie" in first_line or "Dyrektywa" in first_line:
            kb_chunks.append(chunk)
        else:
            user_chunks.append(chunk)

    # ================= KOD DEBUGUJĄCY PODZIAŁ RAG =================
    import logging

    # Wyciągamy unikalne nazwy dokumentów z obu koszyków (tylko pierwsza linijka ze znacznikiem --- DOKUMENT:)
    user_docs = set([c.split('\n')[0] for c in user_chunks])
    kb_docs = set([c.split('\n')[0] for c in kb_chunks])

    logging.info("================ RAPORT RAG: WERYFIKACJA ŹRÓDEŁ ================")
    logging.info(f"ZBIÓR 1 (Firma) - Ilość fragmentów: {len(user_chunks)}")
    logging.info(f"Lista przypisanych plików do ZBIORU 1: {user_docs}")
    logging.info(f"ZBIÓR 2 (Prawo UE) - Ilość fragmentów: {len(kb_chunks)}")
    logging.info(f"Lista przypisanych plików do ZBIORU 2: {kb_docs}")
    logging.info("==================================================================")
    # ----------------------------------

    user_context = "\n\n".join(user_chunks) if user_chunks else "Brak danych z raportów firmy."
    # ================= KONIEC KODU DEBUGUJĄCEGO PODZIAŁ RAG =================

    user_context = "\n\n".join(user_chunks) if user_chunks else "Brak danych z raportów firmy."
    kb_context = "\n\n".join(kb_chunks) if kb_chunks else "Brak danych prawnych z bazy wiedzy."
    hint = TAG_HINTS.get(target_tag, TAG_HINTS["ESG"])
    report_prompt = _build_report_prompt(target_tag, user_context, kb_context, hint)

    # === OpenAI call ===
    self.update_state(
        state="PROGRESS",
        meta={"step": "calling_llm", "stage_pl": "Generowanie raportu przez AI", "progress": 80, "tag": target_tag},
    )
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not api_key.startswith("sk-"):
        raise openai.AuthenticationError(
            message="Brak poprawnego OPENAI_API_KEY",
            response=None,  # type: ignore[arg-type]
            body=None,
        )
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Jesteś analitykiem ESG. Twój jedyny język to poprawny JSON."},
            {"role": "user", "content": report_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        timeout=60.0,
    )
    raw_ai_response = response.choices[0].message.content
    try:
        report_json = json.loads(raw_ai_response)
    except json.JSONDecodeError as exc:
        # Permanent failure — nie retryujemy złego JSON-a
        raise ValueError(f"AI zwrócił nieprawidłowy JSON: {exc}") from exc

    # === Zapis raportu ===
    self.update_state(
        state="PROGRESS",
        meta={"step": "persisting", "stage_pl": "Zapisywanie raportu", "progress": 95, "tag": target_tag},
    )
    try:
        save_report(
            user_id=user_id,
            input_text=f"Generowanie raportu: {target_tag}",
            response_text=raw_ai_response,
            report_type="unified_esg_report",
        )
    except Exception as e:
        logging.warning(f"Nie udało się zapisać raportu do bazy: {e}")

    return {
        "status": "success",
        "mode": "report_generation",
        "kategoria": target_tag,
        "rag_used": True,
        "data": report_json,
    }
