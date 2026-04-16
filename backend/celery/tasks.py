from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
import asyncio

import openai
import requests

from backend.celery.celery_app import celery_app

# ----------------------------------------------------------------
# Cross-OS path resolver
# FastAPI (Windows host) zapisuje pliki do np. C:\...\tmp_uploads\subdir\file
# i przekazuje TYLKO RELATYWNĄ ścieżkę (subdir/file) do tasków.
# Worker w Dockerze rekonstruuje pełną ścieżkę używając WORKER_TMP_ROOT.
# Na tej samej maszynie (bez Dockera) można ustawić WORKER_TMP_ROOT
# na tę samą ścieżkę co UPLOAD_TMP_ROOT.
# ----------------------------------------------------------------
_WORKER_TMP_ROOT = Path(os.getenv("WORKER_TMP_ROOT", "/app/tmp_uploads"))


def _resolve_tmp_path(path_str: str) -> Path:
    """Rozwiąż ścieżkę do pliku tymczasowego.

    - Jeśli relatywna (np. 'task_abc/file.pdf') → sklej z WORKER_TMP_ROOT.
    - Jeśli absolutna i istnieje → użyj bezpośrednio (tryb same-machine).
    - Jeśli absolutna ale nie istnieje → spróbuj WORKER_TMP_ROOT / ostatnie 2 segmenty.
    """
    p = Path(path_str)
    if not p.is_absolute():
        return _WORKER_TMP_ROOT / p
    if p.exists():
        return p
    # Fallback cross-OS: weź 2 ostatnie segmenty (subdir/filename)
    parts = p.parts
    if len(parts) >= 2:
        return _WORKER_TMP_ROOT / parts[-2] / parts[-1]
    return _WORKER_TMP_ROOT / parts[-1]

try:
    from backend.parsers.dispatcher import ParserDispatcher
    from backend.parsers.output_writer import write_result
except ImportError:
    from backend.parsers.dispatcher import ParserDispatcher
    from backend.parsers.output_writer import write_result

try:
    from database.report_repo import save_report
    from database.knowledge_service import add_document_to_knowledge_base
    from database.user_documents_service import process_and_save_user_document
except Exception:
    from .database.report_repo import save_report  # type: ignore
    from .database.knowledge_service import add_document_to_knowledge_base  # type: ignore
    from .database.user_documents_service import process_and_save_user_document  # type: ignore


# ============================================================
# Wspólne stałe konfiguracji retry
# ============================================================

# Transient/network/API-rate błędy — retry jest sensowny
TRANSIENT_EXC = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    ConnectionError,
    TimeoutError,
)


def _cleanup_tmp(path: Path) -> None:
    """Usuń katalog tymczasowy (parent zuploadowanego pliku)."""
    try:
        shutil.rmtree(path.parent, ignore_errors=True)
    except Exception:
        pass


# ============================================================
# ISTNIEJĄCE TASKI — rozszerzone o retry + stage_pl
# ============================================================

@celery_app.task(
    bind=True,
    name="backend.parse_and_store",
    autoretry_for=TRANSIENT_EXC,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=600,
    time_limit=900,
)
def parse_and_store(self, tmp_file_path: str, original_filename: str, user_id: str | None = None) -> Dict[str, Any]:
    """Celery task: parsuj zuploadowany plik, zapisz wynik do output_test_parser i zarejestruj w bazie."""
    self.update_state(
        state="PROGRESS",
        meta={"step": "init", "stage_pl": "Inicjalizacja", "progress": 5, "filename": original_filename},
    )

    path = _resolve_tmp_path(tmp_file_path)
    if not path.exists():
        raise FileNotFoundError(f"Temp file not found: {tmp_file_path}")

    project_root = Path(__file__).resolve().parents[2]
    out_root = project_root / "output_test_parser"

    dispatcher = ParserDispatcher()

    try:
        self.update_state(
            state="PROGRESS",
            meta={"step": "parsing", "stage_pl": "Parsowanie pliku", "progress": 35, "filename": original_filename},
        )
        result = dispatcher.parse(path)

        self.update_state(
            state="PROGRESS",
            meta={"step": "writing_output", "stage_pl": "Zapisywanie wyniku", "progress": 65, "filename": original_filename},
        )
        manifest = write_result(result, out_root)

        # Wyciągnij output_dir z manifestu (potrzebne dla ESG analysis)
        output_dir = None
        if manifest and "output_directory" in manifest:
            output_dir = manifest["output_directory"]
        elif manifest and "files" in manifest and manifest["files"]:
            first_file = manifest["files"][0].get("path", "")
            if first_file:
                output_dir = str(Path(first_file).parent)

        report_id = None
        try:
            self.update_state(
                state="PROGRESS",
                meta={"step": "db_save", "stage_pl": "Zapis do bazy", "progress": 85, "filename": original_filename},
            )
            report_id = save_report(
                user_id=user_id,
                input_text=str(original_filename),
                response_text="Plik przetworzony pomyślnie",
                report_type="parse_result",
            )
        except Exception as db_err:
            print(f"[WARN] DB save failed: {db_err}")

        meta: Dict[str, Any] = {"manifest": manifest, "filename": original_filename}
        if report_id is not None:
            meta["report_id"] = report_id
        if output_dir:
            meta["output_dir"] = output_dir

        return meta
    finally:
        _cleanup_tmp(path)


@celery_app.task(
    bind=True,
    name="backend.parse_and_store_to_knowledge",
    autoretry_for=TRANSIENT_EXC,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=600,
    time_limit=900,
)
def parse_and_store_to_knowledge(
    self,
    tmp_file_path: str,
    original_filename: str,
    tag: str = "general",
    document_type: str = "general",
    version: str = "1.0",
    uploaded_by: str | None = None,
) -> Dict[str, Any]:
    """
    Parsuj plik i zapisz do bazy wiedzy (knowledge_documents + knowledge_chunks bez embeddingów).
    """
    self.update_state(
        state="PROGRESS",
        meta={"step": "init", "stage_pl": "Inicjalizacja", "progress": 5, "filename": original_filename},
    )

    path = _resolve_tmp_path(tmp_file_path)
    if not path.exists():
        raise FileNotFoundError(f"Temp file not found: {tmp_file_path}")

    dispatcher = ParserDispatcher()

    try:
        self.update_state(
            state="PROGRESS",
            meta={"step": "parsing", "stage_pl": "Parsowanie pliku", "progress": 30, "filename": original_filename},
        )
        result = dispatcher.parse(path)

        raw_text = result.text or ""
        if not raw_text and result.pages:
            raw_text = "\n\n".join(result.pages)

        if not raw_text.strip():
            raise ValueError("Nie udało się wyodrębnić tekstu z pliku")

        self.update_state(
            state="PROGRESS",
            meta={"step": "saving_to_knowledge_base", "stage_pl": "Zapisywanie do bazy wiedzy", "progress": 70, "filename": original_filename},
        )

        kb_result = asyncio.run(add_document_to_knowledge_base(
            title=original_filename,
            source=f"upload:{original_filename}",
            raw_text=raw_text,
            tag=tag,
            document_type=document_type,
            version=version,
            uploaded_by=uploaded_by,
        ))

        return {
            "status": "success",
            "filename": original_filename,
            "document_id": kb_result["document_id"],
            "chunks_created": kb_result["chunks_created"],
            "tag": kb_result["tag_assigned"],
            "message": "Dokument sparsowany i zapisany do bazy wiedzy (bez embeddingów)",
        }
    finally:
        _cleanup_tmp(path)


# ============================================================
# NOWY TASK: PROCESSING USER DOCUMENT (RAG uzytkownika)
# parse -> extract -> chunk + embed -> save w user_documents + user_document_chunks
# ============================================================

@celery_app.task(
    bind=True,
    name="backend.process_user_document",
    autoretry_for=TRANSIENT_EXC,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
    soft_time_limit=900,
    time_limit=1200,
)
def process_user_document(
    self,
    tmp_file_path: str,
    original_filename: str,
    user_id: str,
    tag: str = "project_x",
) -> Dict[str, Any]:
    """
    Monolityczny task: parsuj -> wyciągnij tekst -> chunk + embed -> zapis do user_documents(_chunks).
    """
    self.update_state(
        state="PROGRESS",
        meta={"step": "init", "stage_pl": "Inicjalizacja", "progress": 5, "filename": original_filename},
    )

    path = _resolve_tmp_path(tmp_file_path)
    if not path.exists():
        raise FileNotFoundError(f"Temp file not found: {tmp_file_path}")

    try:
        # === PARSOWANIE ===
        self.update_state(
            state="PROGRESS",
            meta={"step": "parsing", "stage_pl": "Parsowanie dokumentu", "progress": 20, "filename": original_filename},
        )
        dispatcher = ParserDispatcher()
        parse_result = dispatcher.parse(path)

        # === EKSTRAKCJA TEKSTU ===
        self.update_state(
            state="PROGRESS",
            meta={"step": "extracting_text", "stage_pl": "Ekstrakcja tekstu", "progress": 35, "filename": original_filename},
        )
        raw_text = parse_result.text or ""
        if not raw_text and parse_result.pages:
            raw_text = "\n\n".join(parse_result.pages)

        if not raw_text.strip():
            raise ValueError("Nie udało się wyodrębnić tekstu z pliku")

        # === CHUNKING + EMBEDDING + ZAPIS ===
        self.update_state(
            state="PROGRESS",
            meta={
                "step": "chunking_and_embedding",
                "stage_pl": "Generowanie embeddingów",
                "progress": 70,
                "filename": original_filename,
            },
        )
        result = asyncio.run(process_and_save_user_document(
            user_id=user_id,
            filename=original_filename,
            raw_text=raw_text,
            file_type=path.suffix.replace(".", "") or "pdf",
            tag=tag,
        ))

        self.update_state(
            state="PROGRESS",
            meta={"step": "finalizing", "stage_pl": "Finalizacja", "progress": 95, "filename": original_filename},
        )

        return {
            "status": "success",
            "filename": original_filename,
            "details": result,
        }
    finally:
        _cleanup_tmp(path)


# ============================================================
# NOWY TASK: PEŁNE PRZETWARZANIE DOKUMENTU BAZY WIEDZY
# parse -> zapis do knowledge_documents/chunks -> generowanie embeddingów
# ============================================================

@celery_app.task(
    bind=True,
    name="backend.process_knowledge_document_full",
    autoretry_for=TRANSIENT_EXC,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
    soft_time_limit=1200,
    time_limit=1500,
)
def process_knowledge_document_full(
    self,
    tmp_file_path: str,
    original_filename: str,
    tag: str = "general",
    document_type: str = "general",
    version: str = "1.0",
    uploaded_by: str | None = None,
) -> Dict[str, Any]:
    """
    Pełny pipeline KB: parsowanie + zapis do knowledge_documents/chunks + generowanie embeddingów.
    """
    # Lokalny import aby uniknąć cyklu przy starcie workera
    from backend.embeddings.embedding_service import generate_embeddings_for_document

    self.update_state(
        state="PROGRESS",
        meta={"step": "init", "stage_pl": "Inicjalizacja", "progress": 5, "filename": original_filename},
    )

    path = _resolve_tmp_path(tmp_file_path)
    if not path.exists():
        raise FileNotFoundError(f"Temp file not found: {tmp_file_path}")

    dispatcher = ParserDispatcher()

    try:
        # === PARSOWANIE ===
        self.update_state(
            state="PROGRESS",
            meta={"step": "parsing", "stage_pl": "Parsowanie pliku", "progress": 20, "filename": original_filename},
        )
        parse_result = dispatcher.parse(path)
        raw_text = parse_result.text or ""
        if not raw_text and parse_result.pages:
            raw_text = "\n\n".join(parse_result.pages)

        if not raw_text.strip():
            raise ValueError("Nie udało się wyodrębnić tekstu z pliku")

        # === ZAPIS DO BAZY WIEDZY ===
        self.update_state(
            state="PROGRESS",
            meta={"step": "saving_to_kb", "stage_pl": "Zapisywanie do bazy wiedzy", "progress": 50, "filename": original_filename},
        )
        kb_result = asyncio.run(add_document_to_knowledge_base(
            title=original_filename,
            source=f"upload:{original_filename}",
            raw_text=raw_text,
            tag=tag,
            document_type=document_type,
            version=version,
            uploaded_by=uploaded_by,
        ))
        document_id = kb_result["document_id"]

        # === GENEROWANIE EMBEDDINGÓW ===
        self.update_state(
            state="PROGRESS",
            meta={
                "step": "generating_embeddings",
                "stage_pl": "Generowanie embeddingów",
                "progress": 80,
                "filename": original_filename,
                "document_id": document_id,
            },
        )
        emb_result = asyncio.run(generate_embeddings_for_document(
            document_id=document_id,
            model="text-embedding-3-small",
            table_name="knowledge_chunks",
        ))

        return {
            "status": "success",
            "filename": original_filename,
            "document_id": document_id,
            "chunks_created": kb_result["chunks_created"],
            "tag": kb_result["tag_assigned"],
            "embeddings": emb_result,
        }
    finally:
        _cleanup_tmp(path)


# ============================================================
# NOWY TASK: INGEST / CHUNK — URL
# fetch URL -> filter keywords -> chunk
# ============================================================

@celery_app.task(
    bind=True,
    name="backend.ingest_chunk_url",
    autoretry_for=TRANSIENT_EXC,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=300,
    time_limit=420,
)
def ingest_chunk_url_task(
    self,
    url: str,
    keywords: Optional[List[str]] = None,
    case_sensitive: bool = False,
    match_all: bool = False,
    context_before: int = 0,
    context_after: int = 0,
    target_tokens: int = 750,
    min_tokens: int = 400,
    max_tokens: int = 1200,
    overlap_tokens: int = 80,
) -> Dict[str, Any]:
    """
    Pobierz URL, przefiltruj wg słów kluczowych, pochunkuj. Zwraca JSON zgodny z IngestResponse.
    """
    from backend.ingestion import (
        ChunkConfig,
        KeywordFilterConfig,
        IngestResponse,
        SourceType,
        fetch_url_text_blocks,
    )
    from backend.ingestion.chunker import chunk_text
    from backend.ingestion.filter import keyword_filter_blocks

    self.update_state(
        state="PROGRESS",
        meta={"step": "fetching", "stage_pl": "Pobieranie strony", "progress": 20, "source": url},
    )
    blocks = fetch_url_text_blocks(url)

    kcfg = KeywordFilterConfig(
        keywords=keywords or [],
        case_sensitive=case_sensitive,
        match_all=match_all,
        context_before=context_before,
        context_after=context_after,
    )
    ccfg = ChunkConfig(
        target_tokens=target_tokens,
        min_tokens=min_tokens,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
    )

    self.update_state(
        state="PROGRESS",
        meta={"step": "filtering", "stage_pl": "Filtrowanie słów kluczowych", "progress": 55, "source": url},
    )
    if keywords:
        filtered_blocks, _ = keyword_filter_blocks(blocks, kcfg)
    else:
        filtered_blocks = blocks

    self.update_state(
        state="PROGRESS",
        meta={"step": "chunking", "stage_pl": "Chunkowanie tekstu", "progress": 80, "source": url},
    )
    joined = "\n\n".join(filtered_blocks)
    chunks_models = chunk_text(joined, ccfg)

    resp = IngestResponse(
        source_type=SourceType.url,
        source=url,
        total_blocks=len(blocks),
        chunks=chunks_models,
        notes=("Brak dopasowań dla słów kluczowych" if keywords and not filtered_blocks else None),
    )
    return resp.model_dump() if hasattr(resp, "model_dump") else resp.dict()


# ============================================================
# NOWY TASK: INGEST / CHUNK — FILE
# parse file -> filter keywords -> chunk
# ============================================================

@celery_app.task(
    bind=True,
    name="backend.ingest_chunk_file",
    autoretry_for=TRANSIENT_EXC,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=600,
    time_limit=900,
)
def ingest_chunk_file_task(
    self,
    tmp_file_path: str,
    original_filename: str,
    keywords: Optional[List[str]] = None,
    case_sensitive: bool = False,
    match_all: bool = False,
    context_before: int = 0,
    context_after: int = 0,
    target_tokens: int = 750,
    min_tokens: int = 400,
    max_tokens: int = 1200,
    overlap_tokens: int = 80,
) -> Dict[str, Any]:
    """
    Parsuj plik, przefiltruj wg słów kluczowych, pochunkuj. Zwraca JSON zgodny z IngestResponse.
    """
    from backend.ingestion import (
        ChunkConfig,
        KeywordFilterConfig,
        IngestResponse,
        SourceType,
    )
    from backend.ingestion.chunker import chunk_text, make_blocks
    from backend.ingestion.filter import keyword_filter_blocks

    self.update_state(
        state="PROGRESS",
        meta={"step": "init", "stage_pl": "Inicjalizacja", "progress": 5, "filename": original_filename},
    )

    path = _resolve_tmp_path(tmp_file_path)
    if not path.exists():
        raise FileNotFoundError(f"Temp file not found: {tmp_file_path}")

    dispatcher = ParserDispatcher()

    try:
        self.update_state(
            state="PROGRESS",
            meta={"step": "parsing", "stage_pl": "Parsowanie pliku", "progress": 30, "filename": original_filename},
        )
        parsed = dispatcher.parse(path)
        text = parsed.text or ""
        if not text and parsed.pages:
            text = "\n\n".join(parsed.pages)
        if not text:
            raise ValueError("Brak tekstu do przetworzenia z pliku")

        blocks = make_blocks(text)

        kcfg = KeywordFilterConfig(
            keywords=keywords or [],
            case_sensitive=case_sensitive,
            match_all=match_all,
            context_before=context_before,
            context_after=context_after,
        )
        ccfg = ChunkConfig(
            target_tokens=target_tokens,
            min_tokens=min_tokens,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )

        self.update_state(
            state="PROGRESS",
            meta={"step": "filtering", "stage_pl": "Filtrowanie słów kluczowych", "progress": 60, "filename": original_filename},
        )
        if keywords:
            filtered_blocks, _ = keyword_filter_blocks(blocks, kcfg)
        else:
            filtered_blocks = blocks

        self.update_state(
            state="PROGRESS",
            meta={"step": "chunking", "stage_pl": "Chunkowanie tekstu", "progress": 85, "filename": original_filename},
        )
        joined = "\n\n".join(filtered_blocks)
        chunks_models = chunk_text(joined, ccfg)

        resp = IngestResponse(
            source_type=SourceType.file,
            source=str(original_filename),
            total_blocks=len(blocks),
            chunks=chunks_models,
            notes=("Brak dopasowań dla słów kluczowych" if keywords and not filtered_blocks else None),
        )
        return resp.model_dump() if hasattr(resp, "model_dump") else resp.dict()
    finally:
        _cleanup_tmp(path)
