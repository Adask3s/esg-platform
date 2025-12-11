from __future__ import annotations
import shutil
from pathlib import Path
from typing import Any, Dict

from backend.celery.celery_app import celery_app

try:
    from backend.parsers.dispatcher import ParserDispatcher
    from backend.parsers.output_writer import write_result
except ImportError:
    from backend.parsers.dispatcher import ParserDispatcher
    from backend.parsers.output_writer import write_result

try:
    from database.report_repo import save_report
except Exception:
    from .database.report_repo import save_report  # type: ignore


@celery_app.task(bind=True, name="backend.parse_and_store")
def parse_and_store(self, tmp_file_path: str, original_filename: str, user_id: int = 1) -> Dict[str, Any]:
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

