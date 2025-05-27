# sentiment_analyzer.py
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# --- Global VADER Analyzer ---
# Initialize it once to save resources
analyzer = SentimentIntensityAnalyzer()

def get_news_sentiment(text):
    """
    Analyzes sentiment of a given text using VADER.
    Returns a compound score between -1 (most negative) and +1 (most positive).
    """
    if not text or not isinstance(text, str):
        return 0.0 # Neutral for no text or invalid input
        
    vs = analyzer.polarity_scores(text)
    return vs['compound']

# --- Example Usage (you'd integrate this into your workflow) ---
def fetch_recent_news_for_stock(ticker_symbol):
    """
    Placeholder: Fetches recent news headlines for a stock.
    In a real system, this would use a news API (e.g., NewsAPI.org, Alpaca, IEX Cloud)
    or scrape reputable financial news sites.
    For yfinance, limited news is available via stock.news
    """
    try:
        stock = yf.Ticker(ticker_symbol)
        news_items = stock.news
        headlines = [item['title'] for item in news_items[:5]] # Get top 5 headlines
        return headlines
    except Exception as e:
        print(f"Error fetching news for {ticker_symbol}: {e}")
        return []

if __name__ == "__main__":
    # Example:
    sample_headlines_bhp = fetch_recent_news_for_stock("BHP.AX") # Make sure ticker is valid
    
    if sample_headlines_bhp:
        print(f"\nRecent News for BHP.AX:")
        for headline in sample_headlines_bhp:
            sentiment_score = get_news_sentiment(headline)
            print(f"  Headline: {headline}")
            print(f"  Sentiment Score: {sentiment_score:.2f}")
            if sentiment_score > 0.05:
                print("  Sentiment: Positive")
            elif sentiment_score < -0.05:
                print("  Sentiment: Negative")
            else:
                print("  Sentiment: Neutral")
    else:
        print("No news found for BHP.AX or error fetching.")

    # Test with generic text
    positive_text = "Great earnings report, company profits soar!"
    negative_text = "Company misses targets, shares plummet."
    neutral_text = "The company will hold its annual general meeting next month."

    print(f"\n'{positive_text}' -> Sentiment: {get_news_sentiment(positive_text):.2f}")
    print(f"'{negative_text}' -> Sentiment: {get_news_sentiment(negative_text):.2f}")
    print(f"'{neutral_text}' -> Sentiment: {get_news_sentiment(neutral_text):.2f}")