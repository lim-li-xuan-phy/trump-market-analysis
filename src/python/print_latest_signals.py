"""
Updates social media posts and financial data, then computes the VADER sentiment score and classifies the post into a topic.
Prints the latest trading signals for "good" configurations to the console.
"""

import os
import sys
import subprocess
from db_manager import get_connection

def run_script(script_name, args):
    # Locate scripts in the same directory as this file
    python_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(python_dir, script_name)
    project_root = os.path.abspath(os.path.join(python_dir, "..", ".."))
    
    print(f"\n==================================================")
    print(f"Running {script_name}...")
    print(f"==================================================")
    
    cmd = [sys.executable, script_path] + args
    result = subprocess.run(cmd, cwd=project_root)
    if result.returncode != 0:
        print(f"\nError: {script_name} failed with exit code {result.returncode}")
        sys.exit(result.returncode)

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    # Pass command-line arguments (like --test) to sub-scripts
    args = sys.argv[1:]
    
    # Update social media posts in DB
    run_script("scrape_posts.py", args)

    # Update market financial data in DB
    run_script("download_market_data.py", args)
    
    # Update sentiment analysis and topics in DB
    run_script("nlp.py", args)
    
    # Compute and print trading signals of latest posts
    configurations = [
        # CL Technology 1-hr & 1-day
        {"asset": "CL", "topic": "Technology", "horizon": "1h"},
        {"asset": "CL", "topic": "Technology", "horizon": "1d"},
        
        # ES all topics except Technology 1-day
        {"asset": "ES", "topic": "China", "horizon": "1d"},
        {"asset": "ES", "topic": "Federal politics", "horizon": "1d"},
        {"asset": "ES", "topic": "Iran war/Oil", "horizon": "1d"},
        {"asset": "ES", "topic": "National security/Immigration", "horizon": "1d"},
        {"asset": "ES", "topic": "Tariffs", "horizon": "1d"},
        
        # YM China 1-hr & 1-day
        {"asset": "YM", "topic": "China", "horizon": "1h"},
        {"asset": "YM", "topic": "China", "horizon": "1d"},
        
        # YM Federal politics 1-day
        {"asset": "YM", "topic": "Federal politics", "horizon": "1d"},
        
        # I_NDX Federal politics 1-day
        {"asset": "I_NDX", "topic": "Federal politics", "horizon": "1d"}
    ]
    
    good_topics = list(set(config["topic"] for config in configurations))

    print("\n======================================================================================================================================================")
    print("                                                              LATEST TRADING SIGNALS                                                                  ")
    print("======================================================================================================================================================")
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        # Fetch the latest 15 posts matching any good configuration topic
        query = """
            SELECT timestamp_utc, message, topic, sentiment_score 
            FROM trump_posts 
            WHERE topic = ANY(%s)
            ORDER BY timestamp_utc DESC 
            LIMIT 15
        """
        cursor.execute(query, (good_topics,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error fetching latest posts from database: {e}")
        sys.exit(1)
        
    if not rows:
        print("No posts found in the database.")
        print("======================================================================================================================================================\n")
        return

    # Print table header
    print(f"{'Timestamp (UTC)':<20} | {'Asset':<6} | {'Topic':<30} | {'Horizon':<8} | {'Score':<6} | {'Signal':<6} | {'Message Snippet'}")
    print("-" * 150)
    
    for r in rows:
        ts = str(r[0])
        msg = str(r[1]).replace('\n', ' ').replace('\r', ' ')
        topic = str(r[2]) if r[2] else "Unclassified"
        score = r[3] if r[3] is not None else 0.0
        
        # Generate trading signals:
        # Long/Buy if sentiment_score >= 0.05
        # Short/Sell if sentiment_score <= -0.05
        # Hold/Neutral otherwise
        if score >= 0.05:
            signal = "LONG"
        elif score <= -0.05:
            signal = "SHORT"
        else:
            signal = "HOLD"
            
        # Format message snippet
        snippet = msg[:60] + "..." if len(msg) > 60 else msg
        
        # Print a signal row for each matching configuration
        for config in configurations:
            if config["topic"] == topic:
                print(f"{ts:<20} | {config['asset']:<6} | {topic:<30} | {config['horizon']:<8} | {score:>6.3f} | {signal:<6} | {snippet}")
        
    print("======================================================================================================================================================\n")

if __name__ == "__main__":
    main()

