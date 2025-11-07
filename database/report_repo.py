from .db_config import get_connection
from datetime import datetime

def save_report(user_id, input_text, response_text, report_type="analysis", status="completed"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO reports (user_id, input_text, response_text, report_type, created_at)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id;
    """, (user_id, input_text, response_text, report_type, datetime.now()))
    report_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    print(f"💾  Raport zapisany w bazie (ID = {report_id})")
    return report_id


def update_report_status(report_id, new_status):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE reports SET report_type = %s WHERE id = %s;", (new_status, report_id))
    conn.commit()
    cur.close()
    conn.close()
    print(f"🟡 Status raportu {report_id} → {new_status}")


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