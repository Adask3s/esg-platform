import assert from "node:assert/strict";
import test from "node:test";

import { parseUserFromToken } from "../../../frontend/src/lib/authToken.js";
import { apiErrorMessage } from "../../../frontend/src/lib/apiErrors.js";
import {
  filenameFromDisposition,
  formatIndicator,
  mapTagToApi,
  scopeFromTag,
} from "../../../frontend/src/lib/reportUtils.js";

function base64UrlJson(payload) {
  return Buffer.from(JSON.stringify(payload), "utf8")
    .toString("base64")
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

function makeToken(payload) {
  return `header.${base64UrlJson(payload)}.signature`;
}

test("parseUserFromToken returns role for valid JWT payload", () => {
  const token = makeToken({ role: "admin", sub: "alice" });

  assert.deepEqual(parseUserFromToken(token), { token, role: "admin" });
});

test("parseUserFromToken is defensive for missing or malformed payloads", () => {
  assert.equal(parseUserFromToken(null), null);
  assert.deepEqual(parseUserFromToken("bad-token"), { token: "bad-token", role: null });
});

test("scopeFromTag maps ESG aliases and preserves fallback", () => {
  assert.equal(scopeFromTag("environmental"), "Environmental");
  assert.equal(scopeFromTag("S"), "Social");
  assert.equal(scopeFromTag("gov"), "Governance");
  assert.equal(scopeFromTag("unknown", "ESG"), "ESG");
});

test("mapTagToApi defaults unknown tags to ESG", () => {
  assert.equal(mapTagToApi(null), "ESG");
  assert.equal(mapTagToApi("social"), "Social");
  assert.equal(mapTagToApi("unknown"), "ESG");
});

test("formatIndicator renders complete and fallback indicators", () => {
  assert.equal(formatIndicator(null), "Metric extraction in progress.");
  assert.equal(formatIndicator({ nazwa: "Scope 1", wartosc: 12, jednostka: "tCO2e" }), "Scope 1: 12 tCO2e");
  assert.equal(formatIndicator({ nazwa: "Missing value" }), "Missing value: -");
});

test("filenameFromDisposition handles UTF-8, ASCII and missing headers", () => {
  assert.equal(filenameFromDisposition(null), "raport_ESG.pdf");
  assert.equal(filenameFromDisposition("attachment; filename=\"raport.pdf\""), "raport.pdf");
  assert.equal(
    filenameFromDisposition("attachment; filename*=UTF-8''raport_%C5%9Brodowisko.pdf"),
    "raport_środowisko.pdf",
  );
});

test("apiErrorMessage renders generic rate limit copy", () => {
  assert.equal(
    apiErrorMessage(429, { detail: "backend-specific" }, "fallback"),
    "Zbyt wiele prób. Odczekaj chwilę i spróbuj ponownie.",
  );
  assert.equal(apiErrorMessage(400, { detail: "Bad request" }, "fallback"), "Bad request");
  assert.equal(apiErrorMessage(500, null, "fallback"), "fallback");
});
