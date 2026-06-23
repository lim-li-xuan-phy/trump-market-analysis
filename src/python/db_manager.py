import os
import psycopg2
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Load environment variables relative to this file's directory
db_manager_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(db_manager_dir, "..", ".env"))
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT")
DB_NAME = os.environ.get("DB_NAME")
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")

def get_connection(database_name=None):
    """
    Establish an active connection to the database. Use for data updating.
    Must close the connection after calling this function.
    """
    db = database_name if database_name is not None else DB_NAME
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=db,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return conn
    except Exception as e:
        print(f"Error connecting to PostgreSQL database '{db}': {e}")
        raise e

def get_engine():
    """
    Establish a lazy engine connection to the database. Use for data modeling. 
    This function is slower than get_connection() but automatically manages resource clean-up.
    """
    return create_engine(f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}')

def create_database_if_not_exists():
    """
    Connect to the database specified in .env or create the database if it doesn't exist.
    """
    try:
        # Connect to database
        conn = get_connection(database_name=DB_NAME)
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Check if database exists
        cursor.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{DB_NAME}'")
        exists = cursor.fetchone()
        
        if not exists:
            print(f"Database '{DB_NAME}' does not exist. Creating...")
            cursor.execute(f"CREATE DATABASE {DB_NAME}")
            print(f"Database '{DB_NAME}' created successfully.")
        else:
            print(f"Database '{DB_NAME}' already exists.")
            
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Could not check/create database '{DB_NAME}' automatically: {e}")
        print("Will proceed assuming database already exists.")

def init_tables():
    """
    Initialize all required database tables.
    """
    create_database_if_not_exists()
    conn = get_connection()
    cursor = conn.cursor()

    # Trump Posts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trump_posts (
            timestamp_utc TIMESTAMP PRIMARY KEY,
            original_timestamp TEXT,
            message TEXT,
            source_url TEXT,
            source_type TEXT,
            sentiment TEXT,
            sentiment_score REAL,
            topic TEXT
        );
    """)
    
    # Futures Contracts Cache table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS futures_contracts_cache (
            date TEXT,
            product TEXT,
            ticker TEXT,
            last_trade_date TEXT,
            PRIMARY KEY (date, product)
        );
    """)
    
    # Market Data 1-Minute table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_data_1min (
            ticker TEXT,
            timestamp_utc TIMESTAMP,
            timestamp_ms BIGINT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (ticker, timestamp_utc)
        );
    """)

    # Market Data 1-Day table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_data_1day (
            ticker TEXT,
            timestamp_utc TIMESTAMP,
            timestamp_ms BIGINT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (ticker, timestamp_utc)
        );
    """)
    
    # Market Data Download Log table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_data_download_log (
            ticker TEXT,
            date TEXT,
            status TEXT,
            PRIMARY KEY (ticker, date)
        );
    """)
    
    # Event Study Results table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_study_results (
            timestamp_utc TIMESTAMP,
            message_snippet TEXT,
            asset TEXT,
            baseline_price REAL,
            baseline_time_offset_sec REAL,
            return_1m REAL, return_5m REAL, return_15m REAL, return_30m REAL, return_1h REAL, return_1d REAL,
            vol_1m REAL, vol_5m REAL, vol_15m REAL, vol_30m REAL, vol_1h REAL, vol_1d REAL,
            beta_1m REAL, beta_5m REAL, beta_15m REAL, beta_30m REAL, beta_1h REAL, beta_1d REAL,
            PRIMARY KEY (timestamp_utc, asset)
        );
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    print("Database tables initialized successfully.")

if __name__ == "__main__":
    init_tables()
