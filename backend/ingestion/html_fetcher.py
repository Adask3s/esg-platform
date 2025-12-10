from __future__ import annotations
from typing import List
import re

import requests
from bs4 import BeautifulSoup

from .chunker import make_blocks, normalize_newlines


def clean_html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Remove script and style elements
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()

    # Convert table to text with simple spacing
    for table in soup.find_all("table"):
        # optional: keep as-is; BeautifulSoup get_text will add spaces/newlines
        pass

    # Join text with newlines between block-level elements
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = normalize_newlines(text)
    return text.strip()


def fetch_url_text_blocks(url: str, timeout: int = 20) -> List[str]:
    resp = requests.get(url, timeout=timeout, headers={
        "User-Agent": "ESG-Ingest/1.0 (+https://example.local)"
    })
    resp.raise_for_status()
    text = clean_html_to_text(resp.text)
    return make_blocks(text)
