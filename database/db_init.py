from db_config import get_connection

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) NOT NULL UNIQUE,
            email VARCHAR(100) UNIQUE,
            password_hash TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
                CREATE TABLE IF NOT EXISTS reports(
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES app_users(id),
                    input_text TEXT,
                    response_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    report_type VARCHAR(50)
                    );
                """)

    # --- użytkownik testowy (żeby nie brakowało foreign key) ---
    cur.execute("""
        INSERT INTO app_users (username, email)
        VALUES ('test_user', 'test@example.com')
        ON CONFLICT (username) DO NOTHING;
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Połączono z bazą PostgreSQL i utworzono tabele.")

if __name__ == "__main__":
    init_db()