try:
    from .db_config import get_connection
except ImportError:
    from db_config import get_connection
from datetime import datetime

def create_user(username: str, email: str | None, password_hash: str, role: str = "user"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO app_users (username, email, password_hash, role, created_at)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (username, email, password_hash, role, datetime.now()),
    )
    user_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return user_id


def get_user_by_username(username: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, email, password_hash, role, created_at FROM app_users WHERE username = %s;", (username,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "username": row[1],
        "email": row[2],
        "password_hash": row[3],
        "role": row[4],
        "created_at": row[5],
    }


def get_user_by_id(user_id: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, email, role, created_at FROM app_users WHERE id = %s;", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "username": row[1], "email": row[2], "role": row[3], "created_at": row[4]}
