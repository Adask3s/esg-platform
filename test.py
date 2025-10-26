from openai import OpenAI

# ⛔ tu wklej swój pełny klucz zamiast tekstu w cudzysłowie
client = OpenAI(api_key="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")

try:
    print("🔑  Łączę się z API...")

    response = client.chat.completions.create(
        model="gpt-4.1-nano",  # pewny, ogólny model
        messages=[
            {"role": "user", "content": "Napisz po polsku jedno zdanie z potwierdzeniem, że połączenie z API działa."}
        ]
    )

    print("\n✅  Odpowiedź z API:")
    print(response.choices[0].message.content)

except Exception as e:
    print("\n❌  Wystąpił błąd:")
    print(repr(e))