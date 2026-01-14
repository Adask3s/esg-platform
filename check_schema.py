import sys
sys.path.insert(0, 'database')
from db_config import get_connection

conn = get_connection()
cur = conn.cursor()
cur.execute("""
    SELECT column_name 
    FROM information_schema.columns 
    WHERE table_name = 'users' 
    ORDER BY ordinal_position;
""")
cols = [row[0] for row in cur.fetchall()]
print('Aktualne kolumny w tabeli users:', cols)

# Dodaj brakujące kolumny
if 'password_hash' not in cols:
    print('Dodawanie kolumny password_hash...')
    cur.execute('ALTER TABLE users ADD COLUMN password_hash TEXT;')
    
if 'created_at' not in cols:
    print('Dodawanie kolumny created_at...')
    cur.execute('ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;')

conn.commit()
cur.close()
conn.close()
print('Schemat zaktualizowany!')
