from __future__ import annotations
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, validator


class SourceType(str, Enum):
    url = "url"
    file = "file"


class KeywordFilterConfig(BaseModel):
    keywords: List[str] = Field(default_factory=list, description="Lista słów kluczowych do wyszukania")
    case_sensitive: bool = False
    match_all: bool = False  # False => dopasuj dowolne, True => wszystkie
    context_before: int = 0  # liczba bloków dołączenia przed trafieniem
    context_after: int = 0   # liczba bloków dołączenia po trafieniu

    @validator("context_before", "context_after")
    def non_negative(cls, v):
        if v < 0:
            raise ValueError("context must be >= 0")
        return v


class ChunkConfig(BaseModel):
    # Rozluźnione minimalne wartości aby umożliwić małe "preview" chunki
    target_tokens: int = Field(750, ge=50, le=4000, description="Docelowa liczba tokenów w fragmencie (min 50)")
    min_tokens: int = Field(400, ge=50, le=3900, description="Minimalna liczba tokenów docelowa przy łączeniu bloków (<= target)")
    max_tokens: int = Field(1200, ge=100, le=6000, description="Maksymalna liczba tokenów w fragmencie (min 100)")
    overlap_tokens: int = Field(80, ge=0, le=400, description="Nakładanie (overlap) w tokenach między kolejnymi fragmentami")
    preserve_structures: bool = True  # nie dziel akapitów/list/tabel jeśli to możliwe

    @validator("max_tokens")
    def ensure_bounds(cls, v, values):
        target = values.get("target_tokens", 750)
        if v < target:
            raise ValueError("max_tokens musi być >= target_tokens")
        return v

    @validator("min_tokens")
    def ensure_min_lt_target(cls, v, values):
        target = values.get("target_tokens", 750)
        if v > target:
            raise ValueError("min_tokens musi być <= target_tokens")
        return v


class Chunk(BaseModel):
    text: str
    token_count: int
    start_block: int
    end_block: int


class IngestResponse(BaseModel):
    source_type: SourceType
    source: str
    total_blocks: int
    chunks: List[Chunk]
    notes: Optional[str] = None


class IngestUrlRequest(BaseModel):
    url: str
    keywords: List[str] = Field(default_factory=list)
    case_sensitive: bool = False
    match_all: bool = False
    context_before: int = 0
    context_after: int = 0
    target_tokens: int = 750
    min_tokens: int = 400
    max_tokens: int = 1200
    overlap_tokens: int = 80

    def to_configs(self) -> tuple[KeywordFilterConfig, ChunkConfig]:
        k = KeywordFilterConfig(
            keywords=self.keywords,
            case_sensitive=self.case_sensitive,
            match_all=self.match_all,
            context_before=self.context_before,
            context_after=self.context_after,
        )
        c = ChunkConfig(
            target_tokens=self.target_tokens,
            min_tokens=self.min_tokens,
            max_tokens=self.max_tokens,
            overlap_tokens=self.overlap_tokens,
        )
        return k, c
