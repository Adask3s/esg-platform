from __future__ import annotations
import shutil
from pathlib import Path
from typing import Any, Dict
import asyncio

from backend.celery.celery_app import celery_app

try:
    from backend.parsers.dispatcher import ParserDispatcher
    from backend.parsers.output_writer import write_result
except ImportError:
    from backend.parsers.dispatcher import ParserDispatcher
    from backend.parsers.output_writer import write_result

try:
    from database.report_repo import save_report
    from database.knowledge_service import add_document_to_knowledge_base
except Exception:
    from .database.report_repo import save_report  # type: ignore
    from .database.knowledge_service import add_document_to_knowledge_base  # type: ignore


@celery_app.task(bind=True, name="backend.parse_and_store")
def parse_and_store(self, tmp_file_path: str, original_filename: str, user_id: str | None = None) -> Dict[str, Any]:
    """Celery task: zparsuj zuploadowany plik i wyslij do output + zapisz w bazie

    Parameters:
    - tmp_file_path: pelna sciezka
    - original_filename: pelna nazwa z uploadu
    - user_id: (placeholder: 1)

    Returns
    -
    """
    self.update_state(state="STARTED", meta={"step": "init"})

    path = Path(tmp_file_path)
    if not path.exists():
        raise FileNotFoundError(f"Temp file not found: {tmp_file_path}")

    project_root = Path(__file__).resolve().parents[2]
    out_root = project_root / "output_test_parser"

    dispatcher = ParserDispatcher()

    try:
        self.update_state(state="PROGRESS", meta={"step": "parsing"})
        result = dispatcher.parse(path)

        self.update_state(state="PROGRESS", meta={"step": "writing_output"})
        manifest = write_result(result, out_root)

        # Wyciągnij output_dir z manifestu (potrzebne dla ESG analysis)
        output_dir = None
        if manifest and "output_directory" in manifest:
            output_dir = manifest["output_directory"]
        elif manifest and "files" in manifest and manifest["files"]:
            # Fallback: weź katalog pierwszego pliku
            first_file = manifest["files"][0].get("path", "")
            if first_file:
                output_dir = str(Path(first_file).parent)

        report_id = None
        try:
            self.update_state(state="PROGRESS", meta={"step": "db_save"})
            report_id = save_report(
                user_id=user_id,
                input_text=str(original_filename),
                response_text="Plik przetworzony pomyślnie",
                report_type="parse_result",
            )
        except Exception as db_err:
            print(f"[WARN] DB save failed: {db_err}")

        meta: Dict[str, Any] = {"manifest": manifest}
        if report_id is not None:
            meta["report_id"] = report_id
        if output_dir:
            meta["output_dir"] = output_dir

        return meta
    finally:
        try:
            shutil.rmtree(path.parent, ignore_errors=True)
        except Exception:
            pass


@celery_app.task(bind=True, name="backend.parse_and_store_to_knowledge")
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
    Celery task: Parsuj plik i automatycznie zapisz do bazy wiedzy (Supabase).

    FLOW:
    1. Parsowanie pliku (PDF/DOCX/Excel) → ekstrakcja tekstu
    2. Chunkowanie tekstu (moduł ingestion)
    3. Zapis do Supabase:
       - knowledge_documents (pełny dokument + metadata)
       - knowledge_chunks (fragmenty tekstu, bez embeddingów)

    Parameters:
    - tmp_file_path: pełna ścieżka do pliku tymczasowego
    - original_filename: oryginalna nazwa pliku
    - tag: tag kategoryzujący (np. 'social', 'environmental', 'governance')
    - document_type: typ dokumentu (domyślnie 'general')
    - version: wersja dokumentu (domyślnie '1.0')

    Returns:
    - Dict z informacją o sukcesie, document_id, liczbie chunków
    """
    self.update_state(state="STARTED", meta={"step": "init", "filename": original_filename})

    path = Path(tmp_file_path)
    if not path.exists():
        raise FileNotFoundError(f"Temp file not found: {tmp_file_path}")

    dispatcher = ParserDispatcher()

    try:
        # === KROK 1: PARSOWANIE ===
        self.update_state(state="PROGRESS", meta={"step": "parsing", "filename": original_filename})
        result = dispatcher.parse(path)

        # Wyciągnij tekst
        raw_text = result.text or ""
        if not raw_text and result.pages:
            raw_text = "\n\n".join(result.pages)

        if not raw_text.strip():
            raise ValueError("Nie udało się wyodrębnić tekstu z pliku")

        # === KROK 2: ZAPIS DO BAZY WIEDZY (z automatycznym chunkowaniem) ===
        self.update_state(state="PROGRESS", meta={"step": "saving_to_knowledge_base", "filename": original_filename})

        kb_result = asyncio.run(add_document_to_knowledge_base(
            title=original_filename,
            source=f"upload:{original_filename}",
            raw_text=raw_text,
            tag=tag,
            document_type=document_type,
            version=version,
            uploaded_by=uploaded_by
        ))

        # === KROK 3: RETURN ===
        return {
            "status": "success",
            "filename": original_filename,
            "document_id": kb_result["document_id"],
            "chunks_created": kb_result["chunks_created"],
            "tag": kb_result["tag_assigned"],
            "message": "Dokument sparsowany i zapisany do bazy wiedzy (bez embeddingów)"
        }

    except Exception as e:
        self.update_state(state="FAILURE", meta={"error": str(e)})
        raise

    finally:
        # Usuń plik tymczasowy
        try:
            shutil.rmtree(path.parent, ignore_errors=True)
        except Exception:
            pass


