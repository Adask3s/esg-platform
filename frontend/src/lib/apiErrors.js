export function apiErrorMessage(status, payload, fallback = "Request failed.") {
  if (status === 429) {
    return "Zbyt wiele prób. Odczekaj chwilę i spróbuj ponownie.";
  }
  return payload?.detail || payload?.message || fallback;
}
