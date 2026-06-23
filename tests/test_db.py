import pytest
from db_manager import get_connection, init_tables, DB_NAME, DB_HOST, DB_PORT

def test_db_env_variables():
    """
    Test whether environment variables are successfully imported.
    """
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

# If database no reachable, continue to other unit tests.
@pytest.mark.skipif(not db_reachable, reason="PostgreSQL database is not reachable. Skipping integration tests.")

def test_db_init_tables():
    """
    Test whether all expected tables exist in the database.
    """
    # Initialize all tables in the database
    init_tables()

    # Query information_schema to verify tables were created
    conn = get_connection()
    cursor = conn.cursor()
    try:
        expected_tables = ['trump_posts', 'market_data_1min', 'market_data_1day', 'futures_contracts_cache', 'market_data_download_log', 'event_study_results']
        for table in expected_tables:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = %s;
            """, (table,))
            row = cursor.fetchone()
            assert row is not None, f"Expected table {table} not found in database."
            assert row[0] == table
    finally:
        cursor.close()
        conn.close()
