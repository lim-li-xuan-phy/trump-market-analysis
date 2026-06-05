"""
Downloads market data through API requests to Massive.com. The user's API key is required in MASSIVE_API_KEY to run this program.

For INDICES and CRYPTO, all available historical data is downloaded. For FUTURES_PRODUCTS, only data of front-month contracts that were active 
on the post dates are downloaded. Note that historical data is limited for free tier Massive accounts.
"""

import os
from dotenv import load_dotenv
import csv
import time
import requests
import pandas as pd
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta

# Constants
MASSIVE_API_KEY = load_dotenv("../.env").get("MASSIVE_API_KEY")
BASE_URL = "https://api.massive.com"
DATA_PATH = "../../data"
POSTS_FILE = f"{DATA_PATH}/trump_posts.csv" 
FUTURES_CACHE_FILE = f"{DATA_PATH}/market/futures_contracts_cache.csv" # Stores the front-month futures that were active at the time of Trump's posts
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
    Load front-month futures data from FUTURES_CACHE_FILE into the `futures_cache` dictionary.
    """
    if os.path.exists(FUTURES_CACHE_FILE):
        try:
            df = pd.read_csv(FUTURES_CACHE_FILE)
            for _, row in df.iterrows():
                futures_cache[(str(row["date"]), str(row["product"]))] = (str(row["ticker"]), str(row["last_trade_date"]))
            print(f"Loaded {len(futures_cache)} front-month futures contract from cache.")
        except Exception as e:
            print(f"Error loading futures contracts cache: {e}")

def save_futures_cache(date_str, product_code, ticker, last_trade_date):
    """
    Save the futures' information to the futures_cache dictionary.
    """
    futures_cache[(date_str, product_code)] = (ticker, last_trade_date)

def save_all_futures_cache():
    """
    Overwrites FUTURES_CACHE_FILE with the entire contents of the `futures_cache` dictionary.
    """
    try:
        os.makedirs(os.path.dirname(FUTURES_CACHE_FILE), exist_ok=True)
        temp_file = FUTURES_CACHE_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "product", "ticker", "last_trade_date"])
            for (date_str, product), (ticker, last_trade) in sorted(futures_cache.items()):
                writer.writerow([date_str, product, ticker, last_trade])
        
        # Replace original file atomically (safely handling potential locks)
        if os.path.exists(FUTURES_CACHE_FILE):
            os.remove(FUTURES_CACHE_FILE)
        os.rename(temp_file, FUTURES_CACHE_FILE)
        print(f"Successfully saved {len(futures_cache)} contracts to cache file.")
    except Exception as e:
        print(f"Error saving futures cache to disk: {e}")

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
            # Skip spread contracts (calendar spreads, butterflies, etc.), identified by ":" or "-" in ticker.
            # Outright futures tickers are plain alphanumeric.
            if ":" in c["ticker"] or "-" in c["ticker"]:
                continue
            # Skip contracts that had already expired before `date_str`.
            if c["last_trade_date"] < date_str:
                continue
            active_contracts.append(c)
        
        # Sort by ascending expiry date last_trade_date
        active_contracts.sort(key=lambda x: x["last_trade_date"])
        if active_contracts:
            ticker = active_contracts[0]["ticker"]
            last_trade_date = active_contracts[0]["last_trade_date"]
            return ticker, last_trade_date
    return None

def find_front_month_futures(product_code, date_str):
    """
    product_code: The product code of a futures contract eg. "CL".
    date_str: The date of a Trump post.

    Search for the front-month futures contracts belonging to a given `product_code`, that were
    active on the date `date_str`.
    """
    # If there is a futures contract matching our requirements already in futures_cache, return that contract.
    if (date_str, product_code) in futures_cache:
        val = futures_cache[(date_str, product_code)]
        if val == ("NONE", "NONE") or val == (None, None) or val[0] == "NONE":
            return None
        return val

    # Send API request to Massive for futures contracts that match our requirements.   
    print(f"Searching for front-month {product_code} futures contracts that were active on {date_str}...")
    result = query_front_month_futures_api(product_code, date_str)
    if result:
        ticker, last_trade_date = result
        save_futures_cache(date_str, product_code, ticker, last_trade_date)
        # Polite crawl-delay to avoid rate limiter
        time.sleep(0.2)
        return ticker, last_trade_date
            
    # If the contract wasn't found (e.g., weekend or holiday), look back up to 5 days.
    # The active contract on a weekend/holiday is the same as the active contract on the preceding trading day.
    curr_dt = datetime.strptime(date_str, "%Y-%m-%d")
    for i in range(1, 6):
        prev_date_str = (curr_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        
        # Check if the lookback date's contract is already in cache
        if (prev_date_str, product_code) in futures_cache:
            val = futures_cache[(prev_date_str, product_code)]
            if val != ("NONE", "NONE") and val != (None, None) and val[0] != "NONE":
                ticker, last_trade_date = val
                print(f"Found active contract {ticker} from cached date {prev_date_str} for {date_str}.")
                save_futures_cache(date_str, product_code, ticker, last_trade_date)
                return ticker, last_trade_date
        else:
            # Query the API for the preceding date
            print(f"Looking back {i} day(s) to {prev_date_str} for active {product_code} contract...")
            val = query_front_month_futures_api(product_code, prev_date_str)
            if val:
                ticker, last_trade_date = val
                print(f"Found active contract {ticker} on {prev_date_str} for {date_str}.")
                # Save both the preceding date and the current date in cache to minimize future requests
                save_futures_cache(prev_date_str, product_code, ticker, last_trade_date)
                save_futures_cache(date_str, product_code, ticker, last_trade_date)
                time.sleep(0.2)
                return ticker, last_trade_date
            else:
                # Cache the preceding date as NONE to avoid querying it again
                save_futures_cache(prev_date_str, product_code, "NONE", "NONE")
                time.sleep(0.2)

    # If still not found after 5 days of lookback, cache this date as NONE
    print(f"Could not find {product_code} futures contract that were active on or up to 5 days before {date_str}. Skipping.")
    save_futures_cache(date_str, product_code, "NONE", "NONE")
    return None

def download_1day_indices_crypto(ticker):
    """
    Send API requests for 1-day frequency data for index and crypto tickers, then save the data to dest_file.
    """

    dest_file = f"{DATA_PATH}/market/daily/{ticker.replace(':', '_')}.csv"
    # Always download daily aggregates to ensure index/crypto data is up-to-date
    print(f"Downloading 1-day aggregates for {ticker}...")
    start_date = EARLIEST_MARKET_DATA_DATE
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{datetime.now().strftime('%Y-%m-%d')}"
    params = {"limit": 50000}
    
    response = api_request(url, params)
    if response and response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        if results:
            os.makedirs(os.path.dirname(dest_file), exist_ok=True)
            with open(dest_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp_utc", "timestamp_ms", "open", "high", "low", "close", "volume"])
                for r in results:
                    ts_utc = format_timestamp_ms(r["t"])
                    writer.writerow([ts_utc, r["t"], r["o"], r["h"], r["l"], r["c"], r.get("v", 0.0)])
            print(f"Saved {len(results)} daily bars for {ticker} to {dest_file}")
        else:
            print(f"No results returned for 1-day frequency {ticker} data.")
    else:
        print(f"Failed to fetch 1-day frequency data for {ticker}.")
    time.sleep(1.0)

def download_1day_futures(ticker, first_trade, last_trade):
    """
    Send API requests for 1-day frequency data for futures, then save the data to dest_file.
    """
    dest_file = f"{DATA_PATH}/market/daily/{ticker}.csv"
    if os.path.exists(dest_file):
        today_str = datetime.now().strftime("%Y-%m-%d")
        if last_trade < today_str:
            # If the contract has already expired, its historical daily data will not change.
            return
        
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
            os.makedirs(os.path.dirname(dest_file), exist_ok=True)
            # Overwrite the daily file to update with any new bars for still-active contracts
            with open(dest_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp_utc", "timestamp_ms", "open", "high", "low", "close", "volume"])
                for r in results:
                    # convert window_start (nanoseconds) to milliseconds
                    timestamp_ms = r["window_start"] // 1000000
                    ts_utc = format_timestamp_ns(r["window_start"])
                    writer.writerow([ts_utc, timestamp_ms, r["open"], r["high"], r["low"], r["close"], r["volume"]])
            print(f"Saved {len(results)} daily bars for futures {ticker} to {dest_file}")
        else:
            print(f"No results returned for 1-day {ticker} futures data.")
    else:
        print(f"Failed to fetch 1-day frequency data for {ticker} futures.")
    time.sleep(1.0)

def download_1min_indices_crypto(ticker, date_str):
    """
    Send API requests for 1-minute frequency data for index and crypto tickers, then save the data to dest_file.
    """
    dest_file = f"{DATA_PATH}/market/minute/{ticker.replace(':', '_')}/{date_str}.csv"
    if os.path.exists(dest_file):
        return
        
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{date_str}/{date_str}"
    params = {"limit": 50000}
    
    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
    response = api_request(url, params)
    
    if response and response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        with open(dest_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_utc", "timestamp_ms", "open", "high", "low", "close", "volume"])
            for r in results:
                ts_utc = format_timestamp_ms(r["t"])
                writer.writerow([ts_utc, r["t"], r["o"], r["h"], r["l"], r["c"], r.get("v", 0.0)])
        print(f"  Downloaded 1-minute data for {ticker} on {date_str} ({len(results)} bars).")
    else:
        # Save a skeleton file (contains only headings, no data) to mark the date `date_str` as queried. 
        # This is to prevent redundant queries on weekends and holidays.
        with open(dest_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_utc", "timestamp_ms", "open", "high", "low", "close", "volume"])
        print(f"  No data for {ticker} on {date_str} (saved empty checkpoint).")
    time.sleep(1.0)

def download_1min_futures(product_code, ticker, date_str):
    """
    Send API requests for 1-minute frequency data for futures, then save the data to dest_file.
    """
    dest_file = f"{DATA_PATH}/market/minute/{product_code}/{date_str}.csv"
    if os.path.exists(dest_file):
        return
        
    # Get range for the single day (date_str and next_date_str)
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    next_date_str = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
    
    url = f"{BASE_URL}/futures/v1/aggs/{ticker}"
    params = {
        "resolution": "1min",
        "window_start.gte": date_str,
        "window_start.lt": next_date_str,
        "limit": 50000
    }
    
    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
    response = api_request(url, params)
    
    if response and response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        with open(dest_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_utc", "timestamp_ms", "open", "high", "low", "close", "volume", "ticker"])
            for r in results:
                timestamp_ms = r["window_start"] // 1000000
                ts_utc = format_timestamp_ns(r["window_start"])
                writer.writerow([ts_utc, timestamp_ms, r["open"], r["high"], r["low"], r["close"], r["volume"], ticker])
        print(f"  Downloaded 1-minute data for futures {product_code} ({ticker}) on {date_str} ({len(results)} bars).")
    else:
        with open(dest_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_utc", "timestamp_ms", "open", "high", "low", "close", "volume", "ticker"])
        print(f"  No data for futures {product_code} ({ticker}) on {date_str} (saved empty checkpoint).") 
    time.sleep(1.0)

def main():
    if not os.path.exists(POSTS_FILE):
        print(f"Error: {POSTS_FILE} not found! Please run scrape_posts.py first.")
        return
        
    print("Loading post dates...")
    df = pd.read_csv(POSTS_FILE)
    post_dates = set()
    for ts in df["timestamp_utc"].dropna():
        try:
            date_str = ts.split(" ")[0]

            # Verify date format
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            post_dates.add(date_str)

            # Add next day to cover returns windows
            next_date = dt + timedelta(days=1)
            post_dates.add(next_date.strftime("%Y-%m-%d"))
        except Exception:
            continue
            
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
                # Get 1-day frequency data from the time period between EARLIEST_MARKET_DATA_DATE and expiry date `last_trade`
                # of this futures contract. The API will only output data within the contract's actual life.
                unique_futures_tickers[ticker] = (product, EARLIEST_MARKET_DATA_DATE, last_trade)
                
    # Save the updated futures cache to disk
    save_all_futures_cache()
                
    # Download 1-day frequency data for all cached futures contracts
    print("Downloading 1-Day Futures Contracts Data...")
    for ticker, (product, first_trade, last_trade) in unique_futures_tickers.items():
        download_1day_futures(ticker, first_trade, last_trade)
        
    # Download 1-min frequency data
    print("Downloading 1-Minute Frequency Data...")
    total_dates = len(sorted_dates)
    for idx, date_str in enumerate(sorted_dates):
        # Check if all 1-min data files for this date already exist to avoid redundant checks and prints
        all_1min_exists = True
        for ticker in INDICES:
            dest_file = f"{DATA_PATH}/market/minute/{ticker.replace(':', '_')}/{date_str}.csv"
            if not os.path.exists(dest_file):
                all_1min_exists = False
                break
        if all_1min_exists:
            for ticker in CRYPTO:
                dest_file = f"{DATA_PATH}/market/minute/{ticker.replace(':', '_')}/{date_str}.csv"
                if not os.path.exists(dest_file):
                    all_1min_exists = False
                    break
        if all_1min_exists:
            for product in FUTURES_PRODUCTS:
                dest_file = f"{DATA_PATH}/market/minute/{product}/{date_str}.csv"
                if not os.path.exists(dest_file):
                    all_1min_exists = False
                    break
        
        if all_1min_exists:
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
                
    # Save the updated futures cache to disk
    save_all_futures_cache()
    print("Successfully completed download of market data.")

if __name__ == "__main__":
    main()
