import pytest
from db_manager import get_connection, init_tables, DB_NAME, DB_HOST, DB_PORT

def test_db_env_variables():
    # Verify environment variables are successfully imported
    assert DB_NAME is not None
    assert DB_HOST is not None
    assert DB_PORT is not None

# Determine if the test database is available to run database schema tests
db_reachable = False
try:
    conn = get_connection()
    conn.close()
    db_reachable = True
except Exception:
    db_reachable = False

@pytest.mark.skipif(not db_reachable, reason="PostgreSQL database is not reachable. Skipping integration tests.")
def test_db_init_tables():
    # Initialize all tables in the database
    init_tables()

    # Query information_schema to verify tables were created
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'trump_posts';
        """)
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 'trump_posts'
    finally:
        cursor.close()
        conn.close()
