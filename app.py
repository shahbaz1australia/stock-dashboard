from flask import Flask, render_template, abort
import yfinance as yf
import pandas as pd
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator
from datetime import datetime, timedelta
import requests
import os

app = Flask(__name__)

NEWS_API_KEY = '54a57b27df13442aaa2d1acb159e2b08'


# --- Helper Functions for Stock Analysis ---

def get_stock_data(ticker_symbol, period="1y"):
    try:
        ticker = yf.Ticker(ticker_symbol)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * 1)  # Fetch 1 year data
        history_df = ticker.history(start=start_date, end=end_date)
        if history_df.empty:
            print(f"No data found for {ticker_symbol}")
            return None
        if 'Close' not in history_df.columns:
            print(f"'Close' column not found in data for {ticker_symbol}")
            return None
        return history_df
    except Exception as e:
        print(f"Error fetching stock price data for {ticker_symbol}: {e}")
        return None


def analyze_sma(df, short_window=20, long_window=50):
    analysis = {
        "name": "Simple Moving Averages (SMA)",
        "signal_key": "NEUTRAL",
        "signal_text": "Neutral / Hold",
        "details": {},
        "explanation": (
            "Simple Moving Averages (SMAs) smooth out price data to show the trend. "
            "A common bullish signal is when a shorter-term SMA (e.g., 20-day) crosses above a "
            "longer-term SMA (e.g., 50-day), suggesting upward momentum. Conversely, a cross below is bearish. "
            "We also look if the current price is above both SMAs (bullish) or below (bearish)."
        )
    }
    if df is None or len(df) < long_window:
        analysis["signal_key"] = "NO_DATA"
        analysis["signal_text"] = "Not enough data"
        analysis["details"] = "Insufficient historical data for SMA calculation."
        return analysis
    try:
        sma_short = SMAIndicator(close=df["Close"], window=short_window, fillna=True)
        sma_long = SMAIndicator(close=df["Close"], window=long_window, fillna=True)
        df["SMA_Short"] = sma_short.sma_indicator()
        df["SMA_Long"] = sma_long.sma_indicator()
        last_price = df["Close"].iloc[-1]
        last_sma_short = df["SMA_Short"].iloc[-1]
        last_sma_long = df["SMA_Long"].iloc[-1]
        prev_sma_short = df["SMA_Short"].iloc[-2] if len(df["SMA_Short"]) > 1 else last_sma_short
        prev_sma_long = df["SMA_Long"].iloc[-2] if len(df["SMA_Long"]) > 1 else last_sma_long

        analysis["details"] = {
            f"Current Price": f"{last_price:.2f}",
            f"SMA {short_window}-day": f"{last_sma_short:.2f}",
            f"SMA {long_window}-day": f"{last_sma_long:.2f}",
        }

        golden_cross = prev_sma_short <= prev_sma_long and last_sma_short > last_sma_long
        death_cross = prev_sma_short >= prev_sma_long and last_sma_short < last_sma_long

        if golden_cross and last_price > last_sma_short:
            analysis["signal_key"] = "STRONG_BUY"
            analysis["signal_text"] = "Strong Buy (Golden Cross & Price Confirmation)"
        elif death_cross and last_price < last_sma_short:
            analysis["signal_key"] = "STRONG_SELL"
            analysis["signal_text"] = "Strong Sell (Death Cross & Price Confirmation)"
        elif last_sma_short > last_sma_long and last_price > last_sma_short:
            analysis["signal_key"] = "BUY"
            analysis["signal_text"] = "Buy (Uptrend)"
        elif last_sma_short < last_sma_long and last_price < last_sma_short:
            analysis["signal_key"] = "SELL"
            analysis["signal_text"] = "Sell (Downtrend)"
        else:
            analysis["signal_key"] = "NEUTRAL"
            analysis["signal_text"] = "Neutral / Hold"
    except Exception as e:
        analysis["signal_key"] = "ERROR"
        analysis["signal_text"] = "Error"
        analysis["details"] = f"Error during SMA analysis: {str(e)}"
        print(f"Error in SMA analysis for {df.index.name if hasattr(df.index, 'name') else 'unknown ticker'}: {e}")
    return analysis


def analyze_rsi(df, window=14, oversold_threshold=30, overbought_threshold=70):
    analysis = {
        "name": "Relative Strength Index (RSI)",
        "signal_key": "NEUTRAL",
        "signal_text": "Neutral / Hold",
        "details": {},
        "explanation": (
            f"The RSI measures the speed and change of price movements. It oscillates between 0 and 100. "
            f"Traditionally, an RSI reading below {oversold_threshold} is considered oversold (potential buy signal), "
            f"and a reading above {overbought_threshold} is considered overbought (potential sell signal). "
            "Traders also look for divergences and centerline crossovers."
        )
    }
    if df is None or len(df) < window + 1:  # RSI needs at least window + 1 periods for initial calculation
        analysis["signal_key"] = "NO_DATA"
        analysis["signal_text"] = "Not enough data"
        analysis["details"] = "Insufficient historical data for RSI calculation."
        return analysis
    try:
        rsi_indicator = RSIIndicator(close=df["Close"], window=window, fillna=True)
        df["RSI"] = rsi_indicator.rsi()
        last_rsi = df["RSI"].iloc[-1]
        analysis["details"] = {f"Current RSI ({window}-day)": f"{last_rsi:.2f}"}

        if last_rsi < oversold_threshold:
            analysis["signal_key"] = "BUY"
            analysis["signal_text"] = "Buy (Oversold)"
        elif last_rsi > overbought_threshold:
            analysis["signal_key"] = "SELL"
            analysis["signal_text"] = "Sell (Overbought)"
        else:
            analysis["signal_key"] = "NEUTRAL"
            analysis["signal_text"] = "Neutral / Hold"
    except Exception as e:
        analysis["signal_key"] = "ERROR"
        analysis["signal_text"] = "Error"
        analysis["details"] = f"Error during RSI analysis: {str(e)}"
        print(f"Error in RSI analysis for {df.index.name if hasattr(df.index, 'name') else 'unknown ticker'}: {e}")
    return analysis


def analyze_macd(df, window_fast=12, window_slow=26, window_sign=9):
    analysis = {
        "name": "MACD (Moving Average Convergence Divergence)",
        "signal_key": "NEUTRAL",
        "signal_text": "Neutral / Hold",
        "details": {},
        "explanation": (
            "MACD shows the relationship between two moving averages of a security's price. "
            "It consists of the MACD line, Signal line, and Histogram. "
            "A bullish signal occurs when the MACD line crosses above the Signal line. "
            "A bearish signal occurs when the MACD line crosses below the Signal line. "
            "The histogram represents the difference between the MACD and Signal lines."
        )
    }
    # MACD needs enough data points for slow MA, then signal line on top of that
    if df is None or len(df) < window_slow + window_sign:
        analysis["signal_key"] = "NO_DATA"
        analysis["signal_text"] = "Not enough data"
        analysis["details"] = "Insufficient historical data for MACD calculation."
        return analysis
    try:
        macd_indicator = MACD(close=df["Close"], window_slow=window_slow, window_fast=window_fast,
                              window_sign=window_sign, fillna=True)
        df["MACD_line"] = macd_indicator.macd()
        df["MACD_signal"] = macd_indicator.macd_signal()
        df["MACD_hist"] = macd_indicator.macd_diff()

        last_macd_line = df["MACD_line"].iloc[-1]
        last_macd_signal = df["MACD_signal"].iloc[-1]
        last_macd_hist = df["MACD_hist"].iloc[-1]
        prev_macd_line = df["MACD_line"].iloc[-2] if len(df["MACD_line"]) > 1 else last_macd_line
        prev_macd_signal = df["MACD_signal"].iloc[-2] if len(df["MACD_signal"]) > 1 else last_macd_signal

        analysis["details"] = {
            "MACD Line": f"{last_macd_line:.2f}",
            "Signal Line": f"{last_macd_signal:.2f}",
            "Histogram": f"{last_macd_hist:.2f}"
        }
        bullish_crossover = prev_macd_line <= prev_macd_signal and last_macd_line > last_macd_signal
        bearish_crossover = prev_macd_line >= prev_macd_signal and last_macd_line < last_macd_signal

        if bullish_crossover:
            if last_macd_hist > 0:
                analysis["signal_key"] = "STRONG_BUY"
                analysis["signal_text"] = "Strong Buy (MACD Bullish Crossover & Positive Histogram)"
            else:
                analysis["signal_key"] = "BUY"
                analysis["signal_text"] = "Buy (MACD Bullish Crossover)"
        elif bearish_crossover:
            if last_macd_hist < 0:
                analysis["signal_key"] = "STRONG_SELL"
                analysis["signal_text"] = "Strong Sell (MACD Bearish Crossover & Negative Histogram)"
            else:
                analysis["signal_key"] = "SELL"
                analysis["signal_text"] = "Sell (MACD Bearish Crossover)"
        elif last_macd_line > last_macd_signal and last_macd_line > 0:  # MACD line is above signal and positive
            analysis["signal_key"] = "NEUTRAL"  # "Hold / Weak Buy" - keep neutral for now
            analysis["signal_text"] = "Hold (MACD Bullish Stance)"
        elif last_macd_line < last_macd_signal and last_macd_line < 0:  # MACD line is below signal and negative
            analysis["signal_key"] = "NEUTRAL"  # "Hold / Weak Sell" - keep neutral
            analysis["signal_text"] = "Hold (MACD Bearish Stance)"
        else:
            analysis["signal_key"] = "NEUTRAL"
            analysis["signal_text"] = "Neutral / Hold"
    except Exception as e:
        analysis["signal_key"] = "ERROR"
        analysis["signal_text"] = "Error"
        analysis["details"] = f"Error during MACD analysis: {str(e)}"
        print(f"Error in MACD analysis for {df.index.name if hasattr(df.index, 'name') else 'unknown ticker'}: {e}")
    return analysis


def get_overall_recommendation_v2(analyses_results, fundamental_data):
    score = 0
    weights = {
        "SMA": 1.5,
        "MACD": 1.2,
        "RSI": 1.0
    }
    signal_scores = {
        "STRONG_BUY": 2,
        "BUY": 1,
        "NEUTRAL": 0,
        "SELL": -1,
        "STRONG_SELL": -2,
        "NO_DATA": 0,
        "ERROR": 0
    }

    active_indicators = 0
    details_log = []  # For debugging score

    for result in analyses_results:
        indicator_name_key = result["name"].split(" ")[0]  # "SMA", "RSI", "MACD"
        signal_key = result.get("signal_key", "NEUTRAL")
        current_score_change = 0

        if signal_key not in ["NO_DATA", "ERROR"]:
            active_indicators += 1
            base_signal_score = signal_scores.get(signal_key, 0)
            indicator_weight = weights.get(indicator_name_key, 1.0)
            current_score_change = base_signal_score * indicator_weight
            score += current_score_change
            details_log.append(
                f"{indicator_name_key}({signal_key}): {base_signal_score} * {indicator_weight} = {current_score_change:.2f}")

    sma_signal = next((r['signal_key'] for r in analyses_results if "SMA" in r['name']), "NEUTRAL")
    rsi_signal = next((r['signal_key'] for r in analyses_results if "RSI" in r['name']), "NEUTRAL")
    macd_signal = next((r['signal_key'] for r in analyses_results if "MACD" in r['name']), "NEUTRAL")

    confluence_bonus = 0
    if sma_signal == "STRONG_BUY" and rsi_signal != "SELL" and (macd_signal == "BUY" or macd_signal == "STRONG_BUY"):
        confluence_bonus = 1.5
        details_log.append(f"Bullish Confluence Bonus: +{confluence_bonus}")
    elif sma_signal == "STRONG_SELL" and rsi_signal != "BUY" and (
            macd_signal == "SELL" or macd_signal == "STRONG_SELL"):
        confluence_bonus = -1.5
        details_log.append(f"Bearish Confluence Penalty: {confluence_bonus}")
    score += confluence_bonus

    fundamental_modifier = 0
    try:
        if fundamental_data.get("Trailing P/E") != "N/A":
            pe = float(fundamental_data["Trailing P/E"])
            if 0 < pe < 15:
                fundamental_modifier += 0.5
            elif pe > 30 and pe < 50:
                fundamental_modifier -= 0.25  # Slightly high
            elif pe >= 50:
                fundamental_modifier -= 0.5  # Very high
        if fundamental_data.get("PEG Ratio") != "N/A":
            peg = float(fundamental_data["PEG Ratio"])
            if 0 < peg < 1:
                fundamental_modifier += 0.5
            elif peg > 2:
                fundamental_modifier -= 0.25
        # Could add more fundamental checks here (e.g., positive EPS growth, reasonable Debt/Equity)
        details_log.append(f"Fundamental Modifier: {fundamental_modifier:+.2f}")
    except ValueError:
        details_log.append("Fundamental Modifier: Error parsing fundamental values.")
        pass
    score += fundamental_modifier

    details_log.append(f"Final Score: {score:.2f}")
    print("Recommendation Details:", "; ".join(details_log))  # Print for debugging

    if active_indicators == 0:
        return "Not Enough Data for Recommendation"

    if score >= 3.5:
        return "Strong Buy Candidate"
    elif score >= 1.5:
        return "Buy Candidate"
    elif score >= 0.5:
        return "Leaning Towards Buy"  # Changed from > 0.5 to >= 0.5
    elif score <= -3.5:
        return "Strong Sell Candidate"
    elif score <= -1.5:
        return "Sell Candidate"
    elif score <= -0.5:
        return "Leaning Towards Sell"  # Changed from < -0.5 to <= -0.5
    else:
        return "Neutral / Hold - Mixed Signals"


def get_real_news_headlines(query_term, company_name, num_headlines=5):
    if not NEWS_API_KEY:
        return [{"title": "NewsAPI key not configured.", "source": "System", "url": "#"}]

    search_query = company_name if company_name and company_name != query_term else f"{query_term} stock"
    if "Ltd" in search_query or "Limited" in search_query:
        search_query = search_query.replace(" Ltd", "").replace(" Limited", "")

    headlines_list = []
    api_urls_tried = []

    # Try with qInTitle first
    url_intitle = (f"https://newsapi.org/v2/everything?"
                   f"qInTitle={requests.utils.quote(search_query)}"
                   f"&language=en&sortBy=publishedAt&pageSize={num_headlines}&apiKey={NEWS_API_KEY}")
    api_urls_tried.append(f"Attempt 1 (qInTitle): {url_intitle}")

    try:
        response = requests.get(url_intitle, timeout=10)
        response.raise_for_status()
        news_data = response.json()

        articles = news_data.get("articles", [])
        if news_data.get("status") == "ok" and articles:
            for article in articles:
                if article.get("title") and article.get("title") != "[Removed]":
                    headlines_list.append({
                        "title": article.get("title"),
                        "source": article.get("source", {}).get("name", "N/A"),
                        "url": article.get("url")
                    })

        # If qInTitle yields few or no results, try a broader query with q
        if not headlines_list or len(headlines_list) < num_headlines // 2:
            url_broader = (f"https://newsapi.org/v2/everything?"
                           f"q={requests.utils.quote(search_query)}"
                           f"&language=en&sortBy=relevance&pageSize={num_headlines}&apiKey={NEWS_API_KEY}")
            api_urls_tried.append(f"Attempt 2 (q broader): {url_broader}")

            response_broader = requests.get(url_broader, timeout=10)
            response_broader.raise_for_status()
            news_data_broader = response_broader.json()
            articles_broader = news_data_broader.get("articles", [])

            if news_data_broader.get("status") == "ok":
                existing_titles = {h['title'] for h in headlines_list}
                for article in articles_broader:
                    if len(headlines_list) >= num_headlines: break
                    title = article.get("title")
                    if title and title != "[Removed]" and title not in existing_titles:
                        headlines_list.append({
                            "title": title,
                            "source": article.get("source", {}).get("name", "N/A"),
                            "url": article.get("url")
                        })
                        existing_titles.add(title)

        if not headlines_list:
            return [{"title": f"No recent headlines found for '{search_query}'.", "source": "NewsAPI", "url": "#"}]
        return headlines_list

    except requests.exceptions.RequestException as e:
        print(f"Error fetching news for {search_query}. URLs tried: {api_urls_tried}. Error: {e}")
        return [{"title": f"Could not fetch news. Error: {e}", "source": "System", "url": "#"}]
    except Exception as e:
        print(f"An unexpected error occurred while fetching news: {e}. URLs: {api_urls_tried}")
        return [{"title": "An unexpected error occurred while fetching news.", "source": "System", "url": "#"}]


# --- Flask Routes ---
@app.route('/')
def index():
    example_tickers = ["CBA.AX", "BHP.AX", "NAB.AX", "AAPL", "GOOGL", "MSFT", "TSLA"]
    return render_template('index_analysis.html', tickers=example_tickers)


@app.route('/dashboard/<string:ticker_symbol>')
def dashboard(ticker_symbol):
    stock_df = get_stock_data(ticker_symbol)

    if stock_df is None or stock_df.empty:
        abort(404,
              description=f"Could not retrieve or process historical price data for ticker '{ticker_symbol}'. Check ticker or try again later.")

    stock_name = ticker_symbol.upper()
    current_price_val = "N/A"
    change_val = "N/A"
    change_percent_val = "N/A"
    yf_ticker_info = None  # Initialize

    try:
        yf_ticker_info = yf.Ticker(ticker_symbol).info
        stock_name = yf_ticker_info.get('longName', yf_ticker_info.get('shortName', ticker_symbol.upper()))

        if not stock_df.empty and 'Close' in stock_df.columns and len(stock_df['Close']) > 0:
            current_price_val = stock_df["Close"].iloc[-1]
            prev_close = stock_df["Close"].iloc[-2] if len(stock_df["Close"]) > 1 else current_price_val
            if isinstance(current_price_val, (int, float)) and isinstance(prev_close, (int, float)):
                change_val = current_price_val - prev_close
                change_percent_val = (change_val / prev_close) * 100 if prev_close != 0 else 0
        else:  # Fallback if history is somehow empty after initial check but info is available
            current_price_val = yf_ticker_info.get('currentPrice', yf_ticker_info.get('regularMarketPreviousClose'))
            prev_close = yf_ticker_info.get('previousClose', current_price_val)
            if isinstance(current_price_val, (int, float)) and isinstance(prev_close, (int, float)):
                change_val = current_price_val - prev_close
                change_percent_val = (change_val / prev_close) * 100 if prev_close != 0 else 0
    except Exception as e:
        print(f"Could not fetch full Ticker info for {ticker_symbol}: {e}")
        # Fallback using only historical data if .info failed
        if not stock_df.empty and 'Close' in stock_df.columns and len(stock_df['Close']) > 0:
            current_price_val = stock_df["Close"].iloc[-1]
            prev_close = stock_df["Close"].iloc[-2] if len(stock_df["Close"]) > 1 else current_price_val
            if isinstance(current_price_val, (int, float)) and isinstance(prev_close, (int, float)):
                change_val = current_price_val - prev_close
                change_percent_val = (change_val / prev_close) * 100 if prev_close != 0 else 0

    # --- Enhanced Fundamental Data ---
    fundamentals = {
        "Market Cap": "N/A", "Trailing P/E": "N/A", "Forward P/E": "N/A", "PEG Ratio": "N/A",
        "Price to Sales (TTM)": "N/A", "Price to Book": "N/A", "Enterprise Value to EBITDA": "N/A",
        "Trailing EPS": "N/A", "Forward EPS": "N/A", "Dividend Yield": "N/A", "Beta": "N/A",
        "52 Week High": "N/A", "52 Week Low": "N/A", "Average Volume (10 day)": "N/A",
        "Profit Margins": "N/A", "Return on Equity (ROE)": "N/A"
    }
    if yf_ticker_info:  # Only process if yf_ticker_info was successfully fetched
        market_cap_raw = yf_ticker_info.get('marketCap')
        if isinstance(market_cap_raw, (int, float)):
            if market_cap_raw >= 1_000_000_000_000:
                fundamentals["Market Cap"] = f"${market_cap_raw / 1_000_000_000_000:.2f}T"
            elif market_cap_raw >= 1_000_000_000:
                fundamentals["Market Cap"] = f"${market_cap_raw / 1_000_000_000:.2f}B"
            elif market_cap_raw >= 1_000_000:
                fundamentals["Market Cap"] = f"${market_cap_raw / 1_000_000:.2f}M"
            else:
                fundamentals["Market Cap"] = f"${market_cap_raw:,.0f}"

        for key, yf_key, factor, prefix, suffix in [
            ("Trailing P/E", 'trailingPE', 1, "", ""), ("Forward P/E", 'forwardPE', 1, "", ""),
            ("PEG Ratio", 'pegRatio', 1, "", ""), ("Price to Sales (TTM)", 'priceToSalesTrailing12Months', 1, "", ""),
            ("Price to Book", 'priceToBook', 1, "", ""),
            ("Enterprise Value to EBITDA", 'enterpriseToEbitda', 1, "", ""),
            ("Trailing EPS", 'trailingEps', 1, "$", ""), ("Forward EPS", 'forwardEps', 1, "$", ""),
            ("Dividend Yield", 'dividendYield', 100, "", "%"), ("Beta", 'beta', 1, "", ""),
            ("52 Week High", 'fiftyTwoWeekHigh', 1, "$", ""), ("52 Week Low", 'fiftyTwoWeekLow', 1, "$", ""),
            ("Profit Margins", 'profitMargins', 100, "", "%"),
            ("Return on Equity (ROE)", 'returnOnEquity', 100, "", "%")
        ]:
            val = yf_ticker_info.get(yf_key)
            if isinstance(val, (int, float)): fundamentals[key] = f"{prefix}{val * factor:.2f}{suffix}"

        avg_vol = yf_ticker_info.get('averageVolume10days', yf_ticker_info.get('averageVolume'))
        if isinstance(avg_vol, (int, float)): fundamentals["Average Volume (10 day)"] = f"{avg_vol:,.0f}"

    # Perform technical analyses
    sma_analysis = analyze_sma(stock_df.copy())
    rsi_analysis = analyze_rsi(stock_df.copy())
    macd_analysis = analyze_macd(stock_df.copy())
    analyses = [sma_analysis, rsi_analysis, macd_analysis]

    overall_recommendation = get_overall_recommendation_v2(analyses, fundamentals)

    query_for_news = stock_name if stock_name != ticker_symbol.upper() else ticker_symbol.upper()
    headlines = get_real_news_headlines(ticker_symbol.upper(), query_for_news)

    data = {
        'ticker': ticker_symbol.upper(),
        'name': stock_name,
        'current_price': f"{current_price_val:.2f}" if isinstance(current_price_val,
                                                                  (int, float)) else current_price_val,
        'change': f"{change_val:+.2f}" if isinstance(change_val, (int, float)) else change_val,
        'change_percent': f"{change_percent_val:+.2f}%" if isinstance(change_percent_val,
                                                                      (int, float)) else change_percent_val,
        'analyses': analyses,
        'overall_recommendation': overall_recommendation,
        'fundamentals': fundamentals,
        'headlines': headlines,
        'disclaimer': "All analysis is for educational purposes only and NOT financial advice. Market conditions can change rapidly. News headlines provided by NewsAPI.org. Fundamental data from Yahoo Finance."
    }
    return render_template('dashboard_analysis.html', data=data)


@app.errorhandler(404)
def page_not_found(e):
    error_description = e.description if hasattr(e, 'description') else "The requested page was not found."
    return render_template('404.html', error_description=error_description), 404


if __name__ == '__main__':
    # Create template files if they don't exist (basic placeholders)
    if not os.path.exists('templates'): os.makedirs('templates')
    for fname, content in {
        'index_analysis.html': """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Stock Analysis Index</title><link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}"></head><body><div class="container"><h1>Stock Analysis Dashboard</h1><p>Select a ticker or enter one below. (ASX: CBA.AX)</p>{% for t in tickers %} <a href="{{ url_for('dashboard', ticker_symbol=t) }}">{{ t }}</a>{% endfor %}<form class="ticker-input-form" onsubmit="const ticker = document.getElementById('tickerInput').value.trim().toUpperCase(); if (ticker) window.location.href = `/dashboard/${ticker}`; return false;"><input type="text" id="tickerInput" placeholder="Enter Ticker (e.g., AAPL)"><button type="submit">Analyze</button></form></div></body></html>""",
        'dashboard_analysis.html': """<!DOCTYPE html><html><head><title>Dashboard</title><link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}"></head><body>Dashboard content here. This is a placeholder.</body></html>""",
        # Actual content is separate
        '404.html': """<!DOCTYPE html><html><head><title>Not Found</title><link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}"></head><body><div class="container"><h1>404 - Not Found</h1><p>{{ error_description }}</p><p><a href="{{ url_for('index') }}">Homepage</a></p></div></body></html>"""
    }.items():
        if not os.path.exists(
                f'templates/{fname}') and fname != 'dashboard_analysis.html':  # dashboard_analysis.html is provided fully below
            with open(f'templates/{fname}', 'w') as f: f.write(content)

    # Create static folder and basic style.css
    if not os.path.exists('static'): os.makedirs('static')
    if not os.path.exists('static/style.css'):
        with open('static/style.css', 'w') as f:
            f.write("""
                body { font-family: Arial, sans-serif; margin: 0; padding: 0; background-color: #f4f7f6; color: #333; }
                .container { max-width: 900px; margin: 20px auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 0 15px rgba(0,0,0,0.1); }
                h1, h2, h3 { color: #2c3e50; }
                a { color: #3498db; text-decoration: none; }
                a:hover { text-decoration: underline; }
                .stock-header { border-bottom: 2px solid #e0e0e0; padding-bottom: 15px; margin-bottom: 20px; }
                .stock-header h1 { margin-bottom: 5px; font-size: 2em;}
                .stock-header .price-info { font-size: 1.2em; }
                .price-info .change-positive { color: #2ecc71; }
                .price-info .change-negative { color: #e74c3c; }
                .overall-recommendation { background-color: #e8f4fd; border-left: 5px solid #3498db; padding: 15px; margin-bottom: 25px; border-radius: 4px; font-size: 1.1em; }
                .overall-recommendation h2 { margin-top: 0; color: #2980b9; }
                .analysis-widget { background-color: #ffffff; border: 1px solid #ddd; border-radius: 5px; margin-bottom: 20px; padding: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
                .analysis-widget h3 { margin-top: 0; border-bottom: 1px solid #eee; padding-bottom: 10px; }
                .analysis-widget .signal { font-weight: bold; margin-bottom: 10px; padding: 8px; border-radius: 4px; display: inline-block; }
                .signal.buy { background-color: #d4efdf; color: #196f3d; border: 1px solid #a9dfbf;}
                .signal.sell { background-color: #fadedb; color: #a93226; border: 1px solid #f5b7b1;}
                .signal.neutral { background-color: #fdf2e9; color: #b9770e; border: 1px solid #f8c471;}
                .signal.error, .signal.not-enough-data { background-color: #ebedef; color: #566573; border: 1px solid #dadee2;}
                .analysis-widget .details p, .fundamental-grid p { margin: 5px 0; font-size: 0.9em; }
                .analysis-widget .details strong, .fundamental-grid strong { color: #555; }
                .analysis-widget .explanation { font-size: 0.9em; color: #555; margin-top: 10px; line-height: 1.5; }
                .fundamental-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 0px 20px; } /* Grid for fundamentals */
                .explanation h4 { margin-top: 15px; margin-bottom: 5px; color: #34495e; }
                .headlines-widget ul { list-style-type: none; padding-left: 0; }
                .headlines-widget li { margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px dashed #eee; }
                .headlines-widget li:last-child { border-bottom: none; }
                .headlines-widget .headline-title a { text-decoration: none; color: #3498db; font-weight: bold; }
                .headlines-widget .headline-source { font-size: 0.85em; color: #777; display: block; margin-top: 3px; }
                .disclaimer { text-align: center; font-size: 0.8em; color: #7f8c8d; margin-top: 30px; padding-top:15px; border-top: 1px solid #e0e0e0;}
                .back-link { display: inline-block; margin-top: 20px; }
                /* Index page specific */
                .ticker-input-form { margin-top: 20px; display: flex; justify-content: center; }
                .ticker-input-form input[type="text"] { padding: 10px; border: 1px solid #ccc; border-radius: 4px 0 0 4px; width: 60%; margin-right: -1px; }
                .ticker-input-form button { padding: 10px 15px; background-color: #2ecc71; color: white; border: none; border-radius: 0 4px 4px 0; cursor: pointer; }
                .ticker-input-form button:hover { background-color: #27ae60; }
                #indexNav a { margin: 0 5px; padding: 5px 10px; background-color:#eee; border-radius:3px;}
            """)

    if not NEWS_API_KEY:
        print(
            "-" * 60 + "\nWARNING: NEWS_API_KEY environment variable is not set.\nReal news headlines will not be fetched.\nPlease get an API key from NewsAPI.org and set the environment variable.\n" + "-" * 60)
    app.run(debug=True)