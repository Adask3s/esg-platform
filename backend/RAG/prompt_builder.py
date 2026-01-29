"""
Moduł odpowiedzialny za budowanie promptu (Context Injection).
Skleja zapytanie użytkownika z fragmentami znalezionymi w bazie (Retrieval),
pilnując limitu tokenów.
"""

import tiktoken
from typing import List, Optional

# Konfiguracja dla gpt-4o-mini / gpt-3.5-turbo / gpt-4
ENCODING_NAME = "cl100k_base"
# Zostawiamy margines na odpowiedź modelu. GPT-4o-mini ma 128k, ale bezpiecznie przyjmijmy mniej dla testów.
MAX_CONTEXT_TOKENS = 12000


def count_tokens(text: str) -> int:
    """Zlicza liczbę tokenów w podanym tekście."""
    try:
        encoding = tiktoken.get_encoding(ENCODING_NAME)
    except Exception:
        # Fallback na domyślny, gdyby nazwa była zła
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


def construct_prompt(
        query: str,
        context_chunks: List[str],
        system_role: str = "Jesteś ekspertem ESG (Environmental, Social, Governance).",
        focused_tag: Optional[str] = None
) -> str:
    """
    Buduje finalny prompt dla LLM.

    Args:
        query: Pytanie użytkownika.
        context_chunks: Lista fragmentów tekstu znalezionych w bazie.
        system_role: Rola systemu (System Prompt).
        focused_tag: Opcjonalny tag (np. 'Environmental'), który dodaje specyficzny kontekst.

    Returns:
        Gotowy string do wysłania do OpenAI.
    """

    # 1. Budowanie instrukcji kontekstowej na podstawie tagu
    tag_instruction = ""
    if focused_tag:
        tag_instruction = f"\nUWAGA: Skup się w swojej analizie wyłącznie na aspekcie: '{focused_tag}'."

    # 2. Przygotowanie szablonu (Szkieletu) promptu
    # Używamy placeholderów {context} żeby potem wstawić tam tekst
    base_prompt_template = f"""
SYSTEM ROLE:
{system_role}
{tag_instruction}

---
CONTEXT (Fragments form Knowledge Base & User Documents):
{{context_placeholder}}

---
USER QUESTION:
"{query}"

INSTRUCTIONS:
Odpowiedz na pytanie używając wyłącznie powyższego kontekstu. Jeśli w kontekście nie ma odpowiedzi, napisz "Nie mam wystarczających informacji w dokumentach".
"""

    # 3. Obliczenie ile miejsca zajmuje sam szkielet (bez chunków)
    # Wstawiamy pusty string w miejsce contextu, żeby policzyć resztę
    base_prompt_text = base_prompt_template.format(context_placeholder="")
    base_tokens = count_tokens(base_prompt_text)

    # 4. Obliczenie dostępnego budżetu na chunki
    available_tokens = MAX_CONTEXT_TOKENS - base_tokens

    if available_tokens < 100:
        # Zabezpieczenie, gdyby pytanie było gigantyczne
        available_tokens = 1000

        # 5. Pętla "upychania" chunków (Context Injection)
    selected_chunks = []
    current_tokens = 0

    for i, chunk in enumerate(context_chunks):
        # Formatowanie pojedynczego chunka (np. dodanie myślnika dla czytelności)
        chunk_formatted = f"\n[Fragment {i + 1}]: {chunk}"
        chunk_tokens = count_tokens(chunk_formatted)

        # Sprawdzamy czy zmieścimy kolejny kawałek
        if current_tokens + chunk_tokens > available_tokens:
            # Limit osiągnięty - przerywamy pętlę
            break

        selected_chunks.append(chunk_formatted)
        current_tokens += chunk_tokens

    # 6. Sklejenie finalnego tekstu
    if selected_chunks:
        final_context_text = "".join(selected_chunks)
    else:
        final_context_text = "Brak pasujących fragmentów w bazie danych."

    final_prompt = base_prompt_template.format(context_placeholder=final_context_text)

    return final_prompt