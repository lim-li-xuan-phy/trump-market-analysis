import nltk
import pytest
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from nlp import classify_topic, get_sentiment

@pytest.fixture(scope="module")
def sia():
    return SentimentIntensityAnalyzer()

# Ensure VADER lexicon is present.
try:
    nltk.data.find('sentiment/vader_lexicon.zip')
except LookupError:
    nltk.download('vader_lexicon')

def test_get_sentiment_positive(sia):
    label, score = get_sentiment("This is a wonderful and fantastic day, I am so happy!", sia)
    assert label == 'positive'
    assert score >= 0.05

    label, score = get_sentiment("Great job by everyone involved!", sia)
    assert label == 'positive'
    assert score >= 0.05

def test_get_sentiment_negative(sia):
    label, score = get_sentiment("This is a terrible, horrible, and very bad situation.", sia)
    assert label == 'negative'
    assert score <= -0.05

    label, score = get_sentiment("Very disappointed with the performance.", sia)
    assert label == 'negative'
    assert score <= -0.05

def test_get_sentiment_neutral(sia):
    label, score = get_sentiment("The meeting is scheduled for tomorrow at 2 PM.", sia)
    assert label == 'neutral'
    assert -0.05 < score < 0.05

    label, score = get_sentiment("I walked to the store.", sia)
    assert label == 'neutral'
    assert -0.05 < score < 0.05

def test_get_sentiment_edge_cases(sia):
    # Non-string input should be treated as empty string and yield neutral
    label, score = get_sentiment(None, sia)
    assert label == 'neutral'
    assert score == 0.0

    label, score = get_sentiment(12345, sia)
    assert label == 'neutral'
    assert score == 0.0

def test_classify_topic_china():
    assert classify_topic("Meeting with President Xi today in Beijing.") == "China"
    assert classify_topic("Chinese exports are increasing.") == "China"

def test_classify_topic_fed():
    assert classify_topic("The Federal Reserve interest rates are too high. Powell must act.") == "Federal politics"
    assert classify_topic("We will support Republicans in the Senate election.") == "Federal politics"

def test_classify_topic_tariffs():
    assert classify_topic("We will impose heavy tariffs on goods from Mexico and Canada.") == "Tariffs"
    assert classify_topic("New trade restrictions will be set soon.") == "Tariffs"

def test_classify_topic_miscellaneous():
    assert classify_topic("Just had a wonderful lunch with the team.") == "Miscellaneous"
    assert classify_topic(None) == "Miscellaneous"
    assert classify_topic(12345) == "Miscellaneous"



