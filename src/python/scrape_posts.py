"""
Scrapes Trump's social media posts from the CNN archive and saves the data into PostgreSQL database.
"""
import sys
import requests
from datetime import date
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta
import dateutil.parser
from db_manager import get_connection
from psycopg2.extras import execute_values

# Constants
POSTS_ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"
EARLIEST_POSTS_DATE = date(2024, 12, 1) # Limit the earliest date of the scraped posts to 1 Dec 2024

def main():
    cutoff_date = EARLIEST_POSTS_DATE
    print(f"Running scraper (filtering posts after earliest scrape date: {cutoff_date}).")
    
    # Get timestamps of posts already in database
    scraped_timestamps = set()
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp_utc FROM trump_posts")
        scraped_timestamps = {row[0].strftime("%Y-%m-%d %H:%M:%S") for row in cursor.fetchall() if row[0] is not None}
        print(f"Found {len(scraped_timestamps)} posts already in database.")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Could not load posts from database: {e}.")
            
    print(f"Fetching posts from {POSTS_ARCHIVE_URL}...")
    try:
        response = requests.get(POSTS_ARCHIVE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        if response.status_code != 200:
            print(f"Error fetching Truth Social archive: {response.status_code}")
            sys.exit(1)
        posts_data = response.json()
    except Exception as e:
        print(f"Exception while fetching Truth Social archive: {e}")
        sys.exit(1)

    print(f"Found {len(posts_data)} total posts in the archive. Processing...")

    new_posts = []
    total_scraped_posts = 0

    # Process posts. The JSON list is sorted newest first.
    for post in posts_data:
        created_at = post.get("created_at")
        if not created_at:
            continue

        try:
            dt = dateutil.parser.parse(created_at)
            doc_date = dt.date()
        except Exception as e:
            print(f"Warning: Could not parse post date {created_at}: {e}")
            continue

        # Stop processing once we reach posts older than cutoff_date
        if doc_date < cutoff_date:
            break

        # Convert to UTC string format '%Y-%m-%d %H:%M:%S'
        try:
            dt_utc = dt.astimezone(ZoneInfo("UTC"))
            utc_ts = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            print(f"Warning: Could not convert date {created_at} to UTC: {e}")
            continue

        # Skip if already in database
        if utc_ts in scraped_timestamps:
            continue

        message = post.get("content", "")
        if not message:
            # Skip empty posts
            continue
        message = message.strip()

        source_url = post.get("url", "https://truthsocial.com/")
        source_type = "Truth Social"
        original_timestamp = created_at

        new_posts.append((utc_ts, original_timestamp, message, source_url, source_type))

    if new_posts:
        print(f"Saving {len(new_posts)} new posts to the database...")
        # Since JSON is newest on top, reverse order to let posts in the database be oldest on top.
        new_posts.reverse()
        try:
            conn = get_connection()
            cursor = conn.cursor()
            insert_query = """
                INSERT INTO trump_posts (timestamp_utc, original_timestamp, message, source_url, source_type)
                VALUES %s
                ON CONFLICT (timestamp_utc) DO NOTHING
            """
            execute_values(cursor, insert_query, new_posts)
            conn.commit()
            total_scraped_posts = len(new_posts)
            cursor.close()
            conn.close()
        except Exception as db_err:
            print(f"Error saving posts to database: {db_err}")
    else:
        print("No new posts to save.")

    print(f"Scraping completed! Added {total_scraped_posts} posts to PostgreSQL database.")

if __name__ == "__main__":
    main()
