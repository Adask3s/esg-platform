export function parseUserFromToken(token) {
  if (!token) return null;

  try {
    const payload = token.split(".")[1];
    if (!payload) return { token, role: null };

    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = atob(normalized);
    const json = JSON.parse(
      decodeURIComponent(
        decoded
          .split("")
          .map((char) => `%${char.charCodeAt(0).toString(16).padStart(2, "0")}`)
          .join("")
      )
    );

    return { token, role: json?.role || null };
  } catch {
    return { token, role: null };
  }
}
