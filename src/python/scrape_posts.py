"""
Scrapes Trump's social media posts from the American Presidency Project archive and saves the data into POSTS_FILE.
"""
import os
import re
import time
import sys
import requests
from bs4 import BeautifulSoup
from datetime import date
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta
import dateutil.parser
from db_manager import get_connection
from psycopg2.extras import execute_values

# Constants
SEARCH_URL_TEMPLATE = "https://www.presidency.ucsb.edu/advanced-search?field-keywords=&field-keywords2=&field-keywords3=&from%5Bdate%5D=&to%5Bdate%5D=&person2=&category2%5B%5D=423&items_per_page=100&order=field_docs_start_date_time_value&sort=desc&page={page}"
BASE_URL = "https://www.presidency.ucsb.edu"
EARLIEST_MARKET_DATA_DATE = date.today() - relativedelta(years=2) # Earliest date of financial data that is accessible on Massive

def clean_timestamp_text(text):
    """
    Clean up raw timestamp string `text` so that it can be parsed into a datetime object.
    """
    text = text.strip()

    # Insert space if 4-digit year is immediately followed by a digit (e.g. 201511:12:50 -> 2015 11:12:50)
    text = re.sub(r'(\b20\d{2})(\d)', r'\1 \2', text)

    # Replace multiple whitespaces with a single whitespace
    text = re.sub(r'\s+', ' ', text)

    return text

def parse_to_utc(timestamp_str, doc_date_str):
    """
    Parse the raw timestamp from the website and convert it to UTC datetime string.
    Falls back to date of daily log document if timestamp_str could not be parsed.
    """
    cleaned_str = clean_timestamp_text(timestamp_str)
    
    # Ensure year is present. If not, get the year from the daily log document date.
    if "201" not in cleaned_str and "202" not in cleaned_str:
        cleaned_str = f"{doc_date_str} {cleaned_str}"
        cleaned_str = clean_timestamp_text(cleaned_str)

    # Parse cleaned string into a datetime object
    try:
        dt = dateutil.parser.parse(cleaned_str)
    except Exception:
        # Fallback to daily log document's date
        try:
            dt = dateutil.parser.parse(doc_date_str)
        except Exception:
            return None

    # Localize to America/New_York (American Presidency Project logs are in Eastern Time)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("America/New_York"))
    else:
        dt = dt.astimezone(ZoneInfo("America/New_York"))
        
    # Convert to UTC
    dt_utc = dt.astimezone(ZoneInfo("UTC"))
    return dt_utc.strftime("%Y-%m-%d %H:%M:%S")

def clean_post_td(td):
    """
    Cleans up raw post string `td` to obtain only the content of the post.
    """
    content_parts = []
    for child in td.contents:
        # Ignore Retweets/Favorites section in tweets
        if child.name == "b" and "Retweets:" in child.get_text():
            break
        if isinstance(child, str):
            content_parts.append(child)
        elif child.name == "br":
            content_parts.append("\n")
        else:
            content_parts.append(child.get_text())
    return "".join(content_parts).strip()

def scrape_document_page(url, doc_date_str, source_type):
    """
    Scrapes the daily log page at the given URL and returns a list of (timestamp_utc, original_timestamp, message) tuples.
    """
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if response.status_code != 200:
            print(f"  Error fetching {url}: {response.status_code}")
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        content_div = soup.find(class_="field-docs-content")
        if not content_div:
            print(f"  No content div found on {url}")
            return []
            
        table = content_div.find("table")
        if not table:
            print(f"  No table found in content of {url}")
            return []
            
        posts = []
        rows = table.find_all("tr")
        for r in rows:
            tds = r.find_all(["td", "th"])
            if len(tds) < 2:
                continue
                
            col0_text = tds[0].get_text().strip()

            # Skip header row
            if "Created" in col0_text or "Tweets" in col0_text:
                continue
                
            orig_ts = tds[0].get_text(" ").strip()
            message = clean_post_td(tds[1])
            
            # Skip empty posts
            if not message:
                continue
                
            utc_ts = parse_to_utc(orig_ts, doc_date_str)
            if utc_ts:
                posts.append((utc_ts, orig_ts, message))
                
        return posts
    except Exception as e:
        print(f"  Exception while scraping {url}: {e}")
        return []



def main():
    test_mode = "--test" in sys.argv
    if test_mode:
        print("Running scraper in TEST MODE (limited to 3 days of posts).")
    
    # Check for already scraped document URLs (checkpointing from DB)
    scraped_urls = set()
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT source_url FROM trump_posts")
        scraped_urls = {row[0] for row in cursor.fetchall() if row[0] is not None}
        print(f"Loaded checkpoint from database: {len(scraped_urls)} daily document pages already scraped.")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Could not load checkpoint from database: {e}.")
            
    page = 0
    total_scraped_posts = 0
    
    while True:
        # Go through all the relevant pages of SEARCH_URL_TEMPLATE
        search_url = SEARCH_URL_TEMPLATE.format(page=page) 
        print(f"Scraping search results page {page + 1}...")
        
        try:
            # Act as a browser so that the server returns a HTML page rather than block the request.
            response = requests.get(search_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if response.status_code != 200:
                print(f"Error fetching search results page {page}: {response.status_code}")
                break

            # Find table containing the search results on search_url
            soup = BeautifulSoup(response.text, "html.parser") # HTML code of the search_url webpage
            table = soup.find("table", class_="views-table")
            if not table:
                print("No search results table found. Done.")
                break

            # Look for row tags belonging to the search results table    
            rows = table.find("tbody").find_all("tr")
            if not rows:
                print("No rows in table. Done.")
                break
                
            print(f"Found {len(rows)} documents on search page {page + 1}.")
            
            new_docs_scraped = 0
            reached_cutoff = False
            for r in rows:
                if test_mode and new_docs_scraped >= 3:
                    break

                # A row containing a search result is expected to have at least 3 columns of data    
                tds = r.find_all("td")
                if len(tds) < 3:
                    continue
                
                # Get the date of the search result document
                doc_date_str = tds[0].get_text().strip()
                
                # Stop scraper once you get to the posts older than EARLIEST_MARKET_DATA_DATE
                try:
                    doc_date = dateutil.parser.parse(doc_date_str).date()
                    if doc_date < EARLIEST_MARKET_DATA_DATE:
                        print(f"Reached date {doc_date_str} which is older than earliest market data ({EARLIEST_MARKET_DATA_DATE}). Stopping scraper.")
                        reached_cutoff = True # Whether we have reached the cutoff date
                        break
                except Exception as e:
                    print(f"Warning: Could not parse document date {doc_date_str}: {e}")
                    
                person = tds[1].get_text().strip()
                title_a = tds[2].find("a") # We want the hyperlink url
                
                if not title_a:
                    continue
                    
                title = title_a.get_text().strip()
                href = title_a.get("href")
                doc_url = BASE_URL + href
                
                # Determine source type (Truth Social or Twitter)
                source_type = "Truth Social" if "Truth Social" in title else "Twitter"
                
                # If search result document has already been scraped, skip the document.
                if doc_url in scraped_urls:
                    continue
                    
                print(f"  Scraping: {title} ({doc_date_str})...")
                posts = scrape_document_page(doc_url, doc_date_str, source_type)
                
                # Write posts to the database
                if posts:
                    try:
                        conn = get_connection()
                        cursor = conn.cursor()
                        insert_query = """
                            INSERT INTO trump_posts (timestamp_utc, original_timestamp, message, source_url, source_type)
                            VALUES %s
                            ON CONFLICT (timestamp_utc) DO NOTHING
                        """
                        records = [(p[0], p[1], p[2], doc_url, source_type) for p in posts]
                        execute_values(cursor, insert_query, records)
                        conn.commit()
                        total_scraped_posts += len(posts)
                        cursor.close()
                        conn.close()
                    except Exception as db_err:
                        print(f"  Error saving posts to database: {db_err}")
                
                scraped_urls.add(doc_url)
                new_docs_scraped += 1
                
                # Polite crawl-delay
                time.sleep(0.5)
            
            print(f"Completed search page {page + 1}. Scraped {new_docs_scraped} new documents.")
            
            if reached_cutoff:
                break
                
            if test_mode:
                print("Test mode: Exiting after page 1.")
                break
            
            # Proceed to the next page in the page list. Stop scraping if there is no next page. 
            pager_next = soup.find("li", class_="next")
            if not pager_next:
                print("No next page link found. Done.")
                break
                
            page += 1
            
        except Exception as e:
            print(f"Exception on search page {page}: {e}")
            break

    print(f"Scraping completed! Added {total_scraped_posts} posts to PostgreSQL.")


if __name__ == "__main__":
    main()
