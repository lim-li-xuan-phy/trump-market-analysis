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

def main():
    parser = argparse.ArgumentParser(description="Trump Posts Sentiment NLP & Topic Classification")
    parser.add_argument('--input', type=str, default='../../data/trump_posts.csv',
                        help='Path to input trump_posts.csv file')
    parser.add_argument('--output', type=str, default='../../data/trump_posts_nlp.csv',
                        help='Path to output trump_posts_nlp.csv file')
    parser.add_argument('--test', action='store_true',
                        help='Run in test mode on first 50 posts')
    
    args = parser.parse_args()
    
    # Handle absolute and relative file paths of input/output files
    input_file = args.input
    if not os.path.exists(input_file):
        print(f"Error: Input file not found at {args.input}")
        sys.exit(1)
    if not os.path.isabs(input_file):
        input_file = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), input_file))
    output_file = args.output
    if not os.path.isabs(output_file):
        output_file = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), output_file))
    
    print(f"Starting sentiment analysis and topic classification...")
    print(f"Input file:  {input_file}")
    print(f"Output file: {output_file}")
    if args.test:
        print("Running in TEST MODE (first 50 posts only)")

    # Read data
    try:
        df = pd.read_csv(input_file)
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        sys.exit(1)
        
    if 'message' not in df.columns:
        print("Error: 'message' column not found in input CSV.")
        sys.exit(1)
        
    if args.test:
        df = df.head(50).copy()
        
    print(f"Loaded {len(df)} posts for analysis.")

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
    
    for idx, row in df.iterrows():
        msg = str(row['message']) if not pd.isna(row['message']) else ""
        
        # Sentiment
        scores = sia.polarity_scores(msg)
        compound = scores['compound']
        sentiment_scores.append(compound)
        
        if compound >= 0.05:
            sentiment_labels.append('positive')
        elif compound <= -0.05:
            sentiment_labels.append('negative')
        else:
            sentiment_labels.append('neutral')
            
        # Topic
        topic = classify_topic(msg)
        topics.append(topic)

    df['sentiment'] = sentiment_labels
    df['sentiment_score'] = sentiment_scores
    df['topic'] = topics

    # Ensure parent directory for output exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    # Save output CSV
    try:
        df.to_csv(output_file, index=False)
        print(f"Analysis completed successfully. Results saved to {output_file}")
    except Exception as e:
        print(f"Error saving output CSV file: {e}")
        sys.exit(1)

    # Print summary statistics
    print("\n" + "="*40)
    print("                NLP SUMMARY STATS                ")
    print("="*40)
    
    total = len(df)
    
    print("\nSentiment Distribution:")
    sent_counts = df['sentiment'].value_counts()
    for label, count in sent_counts.items():
        pct = (count / total) * 100 #percentage
        print(f"  {label:<10}: {count:>5} ({pct:>5.1f}%)")
        
    print("\nTopic Distribution:")
    topic_counts = df['topic'].value_counts()
    for label, count in topic_counts.items():
        pct = (count / total) * 100
        print(f"  {label:<18}: {count:>5} ({pct:>5.1f}%)")
    print("="*40)

if __name__ == "__main__":
    main()
