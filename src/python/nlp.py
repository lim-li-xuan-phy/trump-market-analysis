"""
Performs sentiment analysis on posts and using VADER NLP and classifies posts into preset topics using rules-based 
keyword approach.
"""
import os
import re
import sys
import argparse
import pandas as pd
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from db_manager import get_connection

# Regex patterns for topic classification
TOPIC_KEYWORDS = {
    'China': [
        r'\bchina\b', r'\bchinese\b', r'\bbeijing\b', r'\bxi\b', r'\bshanghai\b', r'\bccp\b'
    ],
    'Federal politics': [
        r'\bfederal\b', r'\breserve\b', r'\bfed\b', r'\brates\b', r'\bpowell\b', r'\bdemocrats?\b', r'\brepublicans?\b', 
        r'\bsenate\b', r'\bcongress\b', r'\bsenators?\b', r'\bcongress(wo)?man\b', r'\bcongressmen\b', r'\bschumer\b', 
        r'\bbiden\b', r'\bhakeem\b', r'\bjeffries\b', r'\bfilibuster\b', r'\bsupreme court\b', r'\bjustices?\b', 
        r'\balito\b', r'\bkavanaugh\b', r'\bcourts?\b', r'\bendorse(ment)?\b', r'\bvote\b', r'\bvoting\b', 
        r'\belections?\b', r'\bprimary\b', r'\bballots?\b', r'\bveto\b', r'\blegislation\b', r'\bbills?\b', 
        r'\bwhite house\b', r'\badministration\b', r'\boz\b', r'\bzeldin\b', r'\brinos?\b', r'\bgovernors?\b', 
        r'\bshapiro\b', r'\bmunir\b', r'\bshehbaz\b', r'\bprime minister\b', r'\bhousing\b', r'\btaxes?\b', 
        r'\bdeductions?\b', r'\bvance\b', r'\bmueller\b', r'\bjobs\b', r'\bunemployment\b', r'\bhome\b', 
        r'\bmichael cohen\b', r'\bhouseholds?\b'
    ],
    'Tariffs': [
        r'\btariffs?\b', r'\btrade\b', r'\bimports?\b', r'\bdut(y|ies)\b', r'\beu\b', r'\beuropean union\b', 
        r'\bnafta\b', r'\busmca\b', r'\bmexico\b', r'\bcanada\b', r'\bcars?\b', r'\btrucks?\b'
    ],
    'Iran war/Oil': [
        r'\boil\b', r'\bcrude\b', r'\bgas\b', r'\bgasoline\b', r'\benergy\b', r'\bpetroleum\b', r'\bdrill(ing)?\b', 
        r'\bpipelines?\b', r'\bfracking\b', r'\bcoal\b', r'\bpower plants?\b',
        r'\biran(ian)?\b', r'\btehran\b', r'\bstrait of hormuz\b', r'\bhormuz\b', r'\bblockade\b',
        r'\blebanon\b', r'\bmines?\b', r'\bships?\b'
    ],
    'Technology': [
        r'\btechnology\b', r'\btech\b', r'\bapple\b', r'\bgoogle\b', r'\bfacebook\b', r'\bmeta\b', r'\bamazon\b', 
        r'\bmicrosoft\b', r'\btim cook\b', r'\belon musk\b', r'\btesla\b', r'\bspacex\b', r'\btwitter\b', 
        r'\btruth social\b', r'\bapps?\b', r'\bwebsites?\b', r'\bonline\b', r'\binternet\b', r'\bai\b', 
        r'\bsemiconductors?\b', r'\bchips?\b'
    ],
    'National security/Immigration': [
        r'\bmilitary\b', r'\bnavy\b', r'\barmy\b', r'\bair force\b', r'\bmarines\b', r'\bpentagon\b', r'\bdefense\b', 
        r'\bwar\b', r'\bceasefires?\b', r'\bborders?\b', r'\bwall\b', r'\bimmigration\b', r'\bimmigrants?\b', r'\bmigrants?\b', 
        r'\bice\b', r'\bborder patrol\b', r'\bnational security\b', r'\bterror(ism|ist|ists)?\b', r'\bweapons?\b', 
        r'\bnuclear\b', r'\bmissiles?\b', r'\bthreats?\b', r'\bbattle(field)?\b', r'\bnaval\b', r'\bsoldiers?\b', 
        r'\bconflict\b', r'\bpeace\b',
        r'\bcharlie kirk\b', r'\bi\.c\.e\.\b', r'\bmaduro\b', r'\bvenezuela\b'
    ]
}

# Compile regular expressions with ignorecase for efficiency
COMPILED_KEYWORDS = {
    topic: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    for topic, patterns in TOPIC_KEYWORDS.items()
}

def classify_topic(text):
    """
    Classifies a text post into a topic by counting occurrences of topic keywords.
    Returns the topic with the highest keyword frequency, or 'Miscellaneous' if no keywords match.
    """
    if not isinstance(text, str):
        return 'Miscellaneous'
        
    scores = {topic: 0 for topic in COMPILED_KEYWORDS}
    for topic, patterns in COMPILED_KEYWORDS.items():
        for pattern in patterns:
            matches = pattern.findall(text)
            scores[topic] += len(matches)
            
    max_score = 0
    best_topic = 'Miscellaneous'
    for topic, score in scores.items():
        if score > max_score:
            max_score = score
            best_topic = topic
            
    return best_topic


def get_sentiment(text, sia):
    """
    Analyzes sentiment of a text using VADER SentimentIntensityAnalyzer.
    Returns a tuple of (sentiment_label, compound_score).
    """
    if not isinstance(text, str):
        text = ""
    scores = sia.polarity_scores(text)
    compound = scores['compound']
    if compound >= 0.05:
        return 'positive', compound
    elif compound <= -0.05:
        return 'negative', compound
    else:
        return 'neutral', compound


def main():
    print(f"Starting sentiment analysis and topic classification...")
    print("Input source: PostgreSQL database (trump_posts table)")
    
    # Read data
    timestamps = []
    messages = []
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        query = "SELECT timestamp_utc, message FROM trump_posts ORDER BY timestamp_utc DESC"
        cursor.execute(query)
        rows = cursor.fetchall()
        for r in rows:
            timestamps.append(r[0])
            messages.append(r[1])
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error reading from PostgreSQL database: {e}")
        sys.exit(1)
        
    total_posts = len(messages)
    print(f"Loaded {total_posts} posts for analysis.")
    if total_posts == 0:
        print("No posts found. Exiting.")
        sys.exit(0)

    # Initialize VADER sentiment analyzer
    try:
        sia = SentimentIntensityAnalyzer()
    except Exception as e:
        print(f"Error initializing VADER Sentiment Analyzer: {e}")
        print("Ensure 'vader_lexicon' is downloaded (python -c \"import nltk; nltk.download('vader_lexicon')\")")
        sys.exit(1)

    print("Running Sentiment and Topic Analysis...")
    
    # Calculate sentiment and topics
    sentiment_scores = []
    sentiment_labels = []
    topics = []
    
    for msg in messages:
        msg_str = str(msg) if not pd.isna(msg) else ""
        
        # Sentiment
        label, score = get_sentiment(msg_str, sia)
        sentiment_labels.append(label)
        sentiment_scores.append(score)
            
        # Topic
        topic = classify_topic(msg_str)
        topics.append(topic)

    # Save output to Database
    try:
        print("Saving results back to PostgreSQL database...")
        conn = get_connection()
        cursor = conn.cursor()
        update_query = """
            UPDATE trump_posts 
            SET sentiment = %s, sentiment_score = %s, topic = %s 
            WHERE timestamp_utc = %s
        """
        records = list(zip(sentiment_labels, sentiment_scores, topics, timestamps))
        cursor.executemany(update_query, records)
        conn.commit()
        cursor.close()
        conn.close()
        print("Successfully updated database records.")
    except Exception as e:
        print(f"Error writing to PostgreSQL database: {e}")
        sys.exit(1)

    # Print summary statistics
    print("\n" + "="*40)
    print("                NLP SUMMARY STATS                ")
    print("="*40)
    
    # Create temporary dataframe for printing of summary stats
    df_stats = pd.DataFrame({
        'sentiment': sentiment_labels,
        'topic': topics
    })
    
    print("\nSentiment Distribution:")
    sent_counts = df_stats['sentiment'].value_counts()
    for label, count in sent_counts.items():
        pct = (count / total_posts) * 100
        print(f"  {label:<10}: {count:>5} ({pct:>5.1f}%)")
        
    print("\nTopic Distribution:")
    topic_counts = df_stats['topic'].value_counts()
    for label, count in topic_counts.items():
        pct = (count / total_posts) * 100
        print(f"  {label:<18}: {count:>5} ({pct:>5.1f}%)")
    print("="*40)

if __name__ == "__main__":
    main()
