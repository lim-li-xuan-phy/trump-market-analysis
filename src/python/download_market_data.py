"""
Downloads market data through API requests to Massive.com. The user's API key is required in MASSIVE_API_KEY to run this program.

For INDICES and CRYPTO, all available historical data is downloaded. For FUTURES_PRODUCTS, only data of front-month contracts that were active 
on the post dates are downloaded. Note that historical data is limited for free tier Massive accounts.
"""

import os
from dotenv import load_dotenv
import time
import requests
import pandas as pd
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta
from db_manager import get_connection
from psycopg2.extras import execute_values

# Constants
load_dotenv("../.env")
MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY")
BASE_URL = "https://api.massive.com"
EARLIEST_MARKET_DATA_DATE = date.today() - relativedelta(years=2) # Earliest date that data is accessible on Massive free tier

# List of financial assets
INDICES = ["I:NDX"]
CRYPTO = ["X:BTCUSD"]
FUTURES_PRODUCTS = ["CL", "ZN", "ES", "YM"] 

def api_request(url, params):
    """
    Make API request to Massive for data. Free tier Massive accounts have rate limits on API requests.
    Once the rate limit is exceeded, Massive returns error 429. So we will retry requests `retries` number of times
    to keep checking if the rate limiter has reset.
    """
    params["apiKey"] = MASSIVE_API_KEY
    retries = 10 # No. of retries left 
    backoff = 2 # No. of seconds to wait between retries
    while retries > 0:
        try:
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 429:
                print(f"Rate limited (ERR 429). Sleeping {backoff} seconds...")
                time.sleep(backoff)
                retries -= 1
                backoff *= 2
                continue
            return response
        except requests.exceptions.RequestException as e:
            print(f"Request exception: {e}. Retrying in {backoff}s...")
            time.sleep(backoff)
            retries -= 1
            backoff *= 2
    return None

def format_timestamp_ms(timestamp_ms):
    """
    Format the timestamp from Massive, in ms, as a UTC datetime string.
    """
    dt = datetime.fromtimestamp(timestamp_ms / 1e3, tz=ZoneInfo("UTC"))
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def format_timestamp_ns(timestamp_ns):
    """
    Format futures timestamp from Massive, in ns, as a UTC datetime string.
    """
    dt = datetime.fromtimestamp(timestamp_ns / 1e9, tz=ZoneInfo("UTC"))
    return dt.strftime("%Y-%m-%d %H:%M:%S")

futures_cache = {}
def load_futures_cache():
    """
    Load front-month futures data from database into the `futures_cache` dictionary.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT date, product, ticker, last_trade_date FROM futures_contracts_cache")
        rows = cursor.fetchall()
        for r in rows:
            futures_cache[(str(r[0]), str(r[1]))] = (str(r[2]), str(r[3]))
        print(f"Loaded {len(futures_cache)} front-month futures contracts from database cache.")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error loading futures contracts cache from database: {e}")

def save_futures_cache(date_str, product_code, ticker, last_trade_date):
    """
    Save the futures' information to the futures_cache dictionary and database.
    """
    futures_cache[(date_str, product_code)] = (ticker, last_trade_date)
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO futures_contracts_cache (date, product, ticker, last_trade_date)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (date, product) DO UPDATE SET
                ticker = EXCLUDED.ticker,
                last_trade_date = EXCLUDED.last_trade_date
        """, (date_str, product_code, ticker, last_trade_date))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error saving futures cache to database: {e}")

def query_front_month_futures_api(product_code, date_str):
    """
    Send API request to Massive for futures contracts active on date_str.
    """
    url = f"{BASE_URL}/futures/v1/contracts"
    params = {
        "product_code": product_code,
        "date": date_str,        # Point-in-time date; API defaults to today if omitted
        "active": "true",        # Only return contracts that were tradeable on `date`
        "ticker.gte": f"{product_code}A",  # Skip spread contracts: spread tickers start with "PRODUCT:"
                                           # where ":" (ASCII 58) < "A" (ASCII 65), so "PRODUCT:" < "PRODUCTA"
        "limit": 1000
    }
    
    response = api_request(url, params)
    if response and response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        active_contracts = []
        for c in results:
            if ":" in c["ticker"] or "-" in c["ticker"]:
                continue
            if c["last_trade_date"] < date_str:
                continue
            active_contracts.append(c)
        
        active_contracts.sort(key=lambda x: x["last_trade_date"])
        if active_contracts:
            ticker = active_contracts[0]["ticker"]
            last_trade_date = active_contracts[0]["last_trade_date"]
            return ticker, last_trade_date
    return None

def find_front_month_futures(product_code, date_str):
    """
    Search for the front-month futures contracts belonging to a given `product_code`, that were
    active on the date `date_str`.
    """
    if (date_str, product_code) in futures_cache:
        val = futures_cache[(date_str, product_code)]
        if val == ("NONE", "NONE") or val == (None, None) or val[0] == "NONE":
            return None
        return val

    print(f"Searching for front-month {product_code} futures contracts that were active on {date_str}...")
    result = query_front_month_futures_api(product_code, date_str)
    if result:
        ticker, last_trade_date = result
        save_futures_cache(date_str, product_code, ticker, last_trade_date)
        time.sleep(0.2)
        return ticker, last_trade_date
            
    curr_dt = datetime.strptime(date_str, "%Y-%m-%d")
    for i in range(1, 6):
        prev_date_str = (curr_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        
        if (prev_date_str, product_code) in futures_cache:
            val = futures_cache[(prev_date_str, product_code)]
            if val != ("NONE", "NONE") and val != (None, None) and val[0] != "NONE":
                ticker, last_trade_date = val
                print(f"Found active contract {ticker} from cached date {prev_date_str} for {date_str}.")
                save_futures_cache(date_str, product_code, ticker, last_trade_date)
                return ticker, last_trade_date
        else:
            print(f"Looking back {i} day(s) to {prev_date_str} for active {product_code} contract...")
            val = query_front_month_futures_api(product_code, prev_date_str)
            if val:
                ticker, last_trade_date = val
                print(f"Found active contract {ticker} on {prev_date_str} for {date_str}.")
                save_futures_cache(prev_date_str, product_code, ticker, last_trade_date)
                save_futures_cache(date_str, product_code, ticker, last_trade_date)
                time.sleep(0.2)
                return ticker, last_trade_date
            else:
                save_futures_cache(prev_date_str, product_code, "NONE", "NONE")
                time.sleep(0.2)

    print(f"Could not find {product_code} futures contract that were active on or up to 5 days before {date_str}. Skipping.")
    save_futures_cache(date_str, product_code, "NONE", "NONE")
    return None

def download_1day_indices_crypto(ticker):
    """
    Send API requests for 1-day frequency data for index and crypto tickers, then save to database.
    """
    print(f"Downloading 1-day aggregates for {ticker}...")
    start_date = EARLIEST_MARKET_DATA_DATE
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{datetime.now().strftime('%Y-%m-%d')}"
    params = {"limit": 50000}
    
    response = api_request(url, params)
    if response and response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        if results:
            try:
                conn = get_connection()
                cursor = conn.cursor()
                insert_query = """
                    INSERT INTO market_data_daily (ticker, timestamp_utc, timestamp_ms, open, high, low, close, volume)
                    VALUES %s
                    ON CONFLICT (ticker, timestamp_utc) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """
                records = []
                for r in results:
                    ts_utc = format_timestamp_ms(r["t"])
                    records.append((ticker.replace(':', '_'), ts_utc, r["t"], r["o"], r["h"], r["l"], r["c"], r.get("v", 0.0)))
                execute_values(cursor, insert_query, records)
                conn.commit()
                cursor.close()
                conn.close()
                print(f"Saved {len(results)} daily bars for {ticker} to database.")
            except Exception as e:
                print(f"Error saving daily bars for {ticker} to database: {e}")
        else:
            print(f"No results returned for 1-day frequency {ticker} data.")
    else:
        print(f"Failed to fetch 1-day frequency data for {ticker}.")
    time.sleep(1.0)

def download_1day_futures(ticker, first_trade, last_trade):
    """
    Send API requests for 1-day frequency data for futures, then save to database.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    if last_trade < today_str:
        # Check if we already have daily data for this expired contract
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM market_data_daily WHERE ticker = %s LIMIT 1", (ticker,))
            exists = cursor.fetchone() is not None
            cursor.close()
            conn.close()
            if exists:
                return
        except Exception as e:
            print(f"Error checking daily data cache for {ticker}: {e}")

    print(f"Downloading 1-day aggregates for futures contract {ticker}...")
    url = f"{BASE_URL}/futures/v1/aggs/{ticker}"
    params = {
        "resolution": "1session",
        "window_start.gte": first_trade,
        "window_start.lte": last_trade,
        "limit": 50000
    }
    
    response = api_request(url, params)
    if response and response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        if results:
            try:
                conn = get_connection()
                cursor = conn.cursor()
                insert_query = """
                    INSERT INTO market_data_daily (ticker, timestamp_utc, timestamp_ms, open, high, low, close, volume)
                    VALUES %s
                    ON CONFLICT (ticker, timestamp_utc) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """
                records = []
                for r in results:
                    timestamp_ms = r["window_start"] // 1000000
                    ts_utc = format_timestamp_ns(r["window_start"])
                    records.append((ticker, ts_utc, timestamp_ms, r["open"], r["high"], r["low"], r["close"], r["volume"]))
                execute_values(cursor, insert_query, records)
                conn.commit()
                cursor.close()
                conn.close()
                print(f"Saved {len(results)} daily bars for futures {ticker} to database.")
            except Exception as e:
                print(f"Error saving daily futures bars for {ticker} to database: {e}")
        else:
            print(f"No results returned for 1-day {ticker} futures data.")
    else:
        print(f"Failed to fetch 1-day frequency data for {ticker} futures.")
    time.sleep(1.0)

def is_date_downloaded_in_db(ticker, date_str):
    """
    Check if a specific date for a ticker has been processed in download log.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status FROM market_data_download_log WHERE ticker = %s AND date = %s",
            (ticker, date_str)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row is not None:
            return True, row[0]
        return False, None
    except Exception as e:
        print(f"Error checking download log: {e}")
        return False, None

def mark_date_downloaded_in_db(ticker, date_str, status):
    """
    Mark a date as downloaded (either success or empty) for a ticker.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO market_data_download_log (ticker, date, status)
            VALUES (%s, %s, %s)
            ON CONFLICT (ticker, date) DO UPDATE SET status = EXCLUDED.status
        """, (ticker, date_str, status))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error updating download log: {e}")

def download_1min_indices_crypto(ticker, date_str):
    """
    Send API requests for 1-minute frequency data for index and crypto tickers, then save to database.
    """
    processed, status = is_date_downloaded_in_db(ticker.replace(':', '_'), date_str)
    if processed:
        return
        
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{date_str}/{date_str}"
    params = {"limit": 50000}
    
    response = api_request(url, params)
    
    if response and response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        
        if results:
            try:
                conn = get_connection()
                cursor = conn.cursor()
                insert_query = """
                    INSERT INTO market_data_minute (ticker, timestamp_utc, timestamp_ms, open, high, low, close, volume)
                    VALUES %s
                    ON CONFLICT (ticker, timestamp_utc) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """
                records = []
                for r in results:
                    ts_utc = format_timestamp_ms(r["t"])
                    records.append((ticker.replace(':', '_'), ts_utc, r["t"], r["o"], r["h"], r["l"], r["c"], r.get("v", 0.0)))
                execute_values(cursor, insert_query, records)
                conn.commit()
                cursor.close()
                conn.close()
                print(f"  Downloaded 1-minute data for {ticker} on {date_str} ({len(results)} bars).")
                mark_date_downloaded_in_db(ticker.replace(':', '_'), date_str, "success")
            except Exception as e:
                print(f"Error saving minute bars for {ticker} to database: {e}")
        else:
            print(f"  No data for {ticker} on {date_str} (marked empty).")
            mark_date_downloaded_in_db(ticker.replace(':', '_'), date_str, "empty")
    else:
        print(f"  Failed to fetch 1-minute data for {ticker} on {date_str} (marked empty).")
        mark_date_downloaded_in_db(ticker.replace(':', '_'), date_str, "empty")
    time.sleep(1.0)

def download_1min_futures(product_code, ticker, date_str):
    """
    Send API requests for 1-minute frequency data for futures, then save to database.
    """
    processed, status = is_date_downloaded_in_db(product_code, date_str)
    if processed:
        return
        
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    next_date_str = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
    
    url = f"{BASE_URL}/futures/v1/aggs/{ticker}"
    params = {
        "resolution": "1min",
        "window_start.gte": date_str,
        "window_start.lt": next_date_str,
        "limit": 50000
    }
    
    response = api_request(url, params)
    
    if response and response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        
        if results:
            try:
                conn = get_connection()
                cursor = conn.cursor()
                insert_query = """
                    INSERT INTO market_data_minute (ticker, timestamp_utc, timestamp_ms, open, high, low, close, volume)
                    VALUES %s
                    ON CONFLICT (ticker, timestamp_utc) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """
                records = []
                for r in results:
                    timestamp_ms = r["window_start"] // 1000000
                    ts_utc = format_timestamp_ns(r["window_start"])
                    records.append((product_code, ts_utc, timestamp_ms, r["open"], r["high"], r["low"], r["close"], r["volume"]))
                execute_values(cursor, insert_query, records)
                conn.commit()
                cursor.close()
                conn.close()
                print(f"  Downloaded 1-minute data for futures {product_code} ({ticker}) on {date_str} ({len(results)} bars).")
                mark_date_downloaded_in_db(product_code, date_str, "success")
            except Exception as e:
                print(f"Error saving minute futures bars for {product_code} to database: {e}")
        else:
            print(f"  No data for futures {product_code} ({ticker}) on {date_str} (marked empty).")
            mark_date_downloaded_in_db(product_code, date_str, "empty")
    else:
        print(f"  Failed to fetch 1-minute data for futures {product_code} ({ticker}) on {date_str} (marked empty).")
        mark_date_downloaded_in_db(product_code, date_str, "empty")
    time.sleep(1.0)

def main():
    print("Loading post dates from PostgreSQL database...")
    post_dates = set()
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp_utc FROM trump_posts WHERE topic IS NOT NULL AND topic != 'Miscellaneous'")
        rows = cursor.fetchall()
        for r in rows:
            ts = str(r[0])
            date_str = ts.split(" ")[0]
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            post_dates.add(date_str)
            next_date = dt + timedelta(days=1)
            post_dates.add(next_date.strftime("%Y-%m-%d"))
        cursor.close()
        conn.close()
        print(f"Loaded {len(post_dates)} unique dates from database.")
    except Exception as e:
        print(f"Error loading post dates from database: {e}.")
        return
            
    sorted_dates = sorted(list(post_dates))
    import sys
    test_mode = "--test" in sys.argv
    if test_mode:
        print("Running in TEST MODE: Limiting to first 3 dates for search of relevant futures contracts and download of 1-min frequency data.")
        sorted_dates = sorted_dates[:3]
        
    print(f"Identified {len(sorted_dates)} unique dates (including post dates and next days) for downloading front-month futures data.")
    
    # Load cache of front-month futures contracts
    load_futures_cache()
    
    # Download daily data for indices & crypto
    print("Downloading daily index & crypto data...")
    for ticker in INDICES + CRYPTO:
        download_1day_indices_crypto(ticker)
        
    # Search for and cache all futures contracts which were active at social media post dates.
    print("Searching and caching relevant futures contracts...")
    unique_futures_tickers = {}  # ticker -> (product_code, first_trade_date, last_trade_date)
    
    for date_str in sorted_dates:
        for product in FUTURES_PRODUCTS:
            result = find_front_month_futures(product, date_str)
            if result:
                ticker, last_trade = result
                unique_futures_tickers[ticker] = (product, EARLIEST_MARKET_DATA_DATE, last_trade)
                
    # Download 1-day frequency data for all cached futures contracts
    print("Downloading 1-Day Futures Contracts Data...")
    for ticker, (product, first_trade, last_trade) in unique_futures_tickers.items():
        download_1day_futures(ticker, first_trade, last_trade)
        
    # Download 1-min frequency data
    print("Downloading 1-Minute Frequency Data...")
    total_dates = len(sorted_dates)
    for idx, date_str in enumerate(sorted_dates):
        # Check if all 1-min data has already been processed (either success or empty)
        all_1min_processed = True
        for ticker in INDICES:
            processed, _ = is_date_downloaded_in_db(ticker.replace(':', '_'), date_str)
            if not processed:
                all_1min_processed = False
                break
        if all_1min_processed:
            for ticker in CRYPTO:
                processed, _ = is_date_downloaded_in_db(ticker.replace(':', '_'), date_str)
                if not processed:
                    all_1min_processed = False
                    break
        if all_1min_processed:
            for product in FUTURES_PRODUCTS:
                processed, _ = is_date_downloaded_in_db(product, date_str)
                if not processed:
                    all_1min_processed = False
                    break
        
        if all_1min_processed:
            continue
            
        print(f"[{idx+1}/{total_dates}] Processing date: {date_str}")
        
        # Indices
        for ticker in INDICES:
            download_1min_indices_crypto(ticker, date_str)
            
        # Crypto
        for ticker in CRYPTO:
            download_1min_indices_crypto(ticker, date_str)
            
        # Futures
        for product in FUTURES_PRODUCTS:
            result = find_front_month_futures(product, date_str)
            if result:
                futures_ticker, _ = result
                download_1min_futures(product, futures_ticker, date_str)
                
    print("Successfully completed download of market data.")

if __name__ == "__main__":
    main()
