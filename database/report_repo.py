from .db_config import get_connection
from datetime import datetime

def save_report(user_id, input_text, response_text, report_type="analysis", used_chunks=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO reports (user_id, input_text, response_text, report_type, created_at, used_chunks)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
    """, (user_id, input_text, response_text, report_type, datetime.now(), used_chunks))
    report_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    print(f"💾 Raport zapisany w bazie (ID = {report_id})")
    return report_id

def get_reports_by_user(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, report_type, created_at 
        FROM reports
        WHERE user_id = %s
        ORDER BY created_at DESC;
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_report_by_id(report_id, user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, input_text, response_text, report_type, created_at, used_chunks 
        FROM reports
        WHERE id = %s AND user_id = %s;
    """, (report_id, user_id))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        return {
            "id": row[0],
            "input_text": row[1],
            "response_text": row[2],
            "report_type": row[3],
            "created_at": row[4],
            "used_chunks": row[5]
        }
    return None

# =========== FUNKCJA DO USUWANIA WYGENEROWANEGO RAPORTU UŻYTKOWNIKA ===============
def clear_report_evidence_for_user(user_id: str) -> int:
    """Czysci zapisane fragmenty zrodlowe (`used_chunks`) w raportach uzytkownika."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE reports
            SET used_chunks = NULL
            WHERE user_id = %s AND used_chunks IS NOT NULL;
            """,
            (user_id,),
        )
        cleared_count = cur.rowcount
        conn.commit()
        return cleared_count
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


def delete_report(report_id: str, user_id: str) -> bool:
    """Usuwa raport z bazy. Zwraca True jeśli usunięto, False jeśli raport nie istniał."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            DELETE FROM reports
            WHERE id = %s AND user_id = %s;
        """, (report_id, user_id))

        deleted_count = cur.rowcount
        conn.commit()

        return deleted_count > 0
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()
