from flask import Flask, render_template, abort, jsonify  # Added jsonify
import yfinance as yf
import pandas as pd
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator
from datetime import datetime, timedelta
import requests
import os
import traceback  # Added for detailed error logging

app = Flask(__name__)

# --- IMPORTANT: Use Environment Variable for API Key ---
# Make sure to set NEWS_API_KEY in your Render environment variables
NEWS_API_KEY = '54a57b27df13442aaa2d1acb159e2b08'

if not NEWS_API_KEY:
    print("-" * 60)
    print("WARNING: NEWS_API_KEY environment variable is NOT SET.")
    print("Real news headlines will not be fetched effectively or might fail.")
    print("Please get a new API key from NewsAPI.org and set it in Render's environment variables.")
    print("-" * 60)


# --- Helper Functions for Stock Analysis ---

def get_stock_data(ticker_symbol, period="1y"):
    print(f"[LOG] get_stock_data: Attempting to fetch yfinance data for: {ticker_symbol}, period: {period}")
    try:
        ticker = yf.Ticker(ticker_symbol)
        end_date = datetime.now()
        # For 1 year of data, yfinance usually handles the exact start date well.
        # Let's ensure we ask for enough to cover typical TA window needs.
        start_date_calc = end_date - timedelta(days=400)  # Slightly more than 1 year for TA calculations

        history_df = ticker.history(start=start_date_calc, end=end_date, timeout=20)  # Added timeout

        if history_df.empty:
            print(f"[LOG] get_stock_data: No historical data found for {ticker_symbol} from yfinance.")
            # Attempt to get .info as a fallback to see if the ticker is valid at all
            try:
                info = ticker.info
                if info and info.get('regularMarketPrice'):
                    print(
                        f"[LOG] get_stock_data: Historical data empty, but .info found for {ticker_symbol}. Ticker likely valid but might lack history for the period.")
                else:
                    print(
                        f"[LOG] get_stock_data: Historical data empty and .info also seems sparse or invalid for {ticker_symbol}.")
            except Exception as e_info:
                print(
                    f"[LOG] get_stock_data: Error trying to get .info after empty history for {ticker_symbol}: {e_info}")
            return None

        if 'Close' not in history_df.columns:
            print(
                f"[LOG] get_stock_data: 'Close' column not found in data for {ticker_symbol}. Columns: {history_df.columns}")
            return None

        print(f"[LOG] get_stock_data: Successfully fetched {len(history_df)} rows for {ticker_symbol}.")
        return history_df
    except Exception as e:
        print(f"[ERROR] get_stock_data: Error fetching stock price data for {ticker_symbol}: {e}")
        print(traceback.format_exc())
        return None


def analyze_sma(df, short_window=20, long_window=50):
    # ... (SMA analysis code remains the same - no changes needed for this specific issue)
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
        print(f"[ERROR] analyze_sma: Error for {df.index.name if hasattr(df.index, 'name') else 'unknown ticker'}: {e}")
        print(traceback.format_exc())
    return analysis


def analyze_rsi(df, window=14, oversold_threshold=30, overbought_threshold=70):
    # ... (RSI analysis code remains the same)
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
    if df is None or len(df) < window + 1:
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
        print(f"[ERROR] analyze_rsi: Error for {df.index.name if hasattr(df.index, 'name') else 'unknown ticker'}: {e}")
        print(traceback.format_exc())
    return analysis


def analyze_macd(df, window_fast=12, window_slow=26, window_sign=9):
    # ... (MACD analysis code remains the same)
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
        elif last_macd_line > last_macd_signal and last_macd_line > 0:
            analysis["signal_key"] = "NEUTRAL"
            analysis["signal_text"] = "Hold (MACD Bullish Stance)"
        elif last_macd_line < last_macd_signal and last_macd_line < 0:
            analysis["signal_key"] = "NEUTRAL"
            analysis["signal_text"] = "Hold (MACD Bearish Stance)"
        else:
            analysis["signal_key"] = "NEUTRAL"
            analysis["signal_text"] = "Neutral / Hold"
    except Exception as e:
        analysis["signal_key"] = "ERROR"
        analysis["signal_text"] = "Error"
        analysis["details"] = f"Error during MACD analysis: {str(e)}"
        print(
            f"[ERROR] analyze_macd: Error for {df.index.name if hasattr(df.index, 'name') else 'unknown ticker'}: {e}")
        print(traceback.format_exc())
    return analysis


def get_overall_recommendation_v2(analyses_results, fundamental_data):
    # ... (Overall recommendation logic remains the same)
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
    details_log = []

    for result in analyses_results:
        indicator_name_key = result["name"].split(" ")[0]
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
                fundamental_modifier -= 0.25
            elif pe >= 50:
                fundamental_modifier -= 0.5
        if fundamental_data.get("PEG Ratio") != "N/A":
            peg = float(fundamental_data["PEG Ratio"])
            if 0 < peg < 1:
                fundamental_modifier += 0.5
            elif peg > 2:
                fundamental_modifier -= 0.25
        details_log.append(f"Fundamental Modifier: {fundamental_modifier:+.2f}")
    except ValueError:
        details_log.append("Fundamental Modifier: Error parsing fundamental values.")
        pass  # Keep going if fundamental parsing fails
    score += fundamental_modifier

    details_log.append(f"Final Score: {score:.2f}")
    print("[LOG] Recommendation Details:", "; ".join(details_log))

    if active_indicators == 0: return "Not Enough Data for Recommendation"
    if score >= 3.5:
        return "Strong Buy Candidate"
    elif score >= 1.5:
        return "Buy Candidate"
    elif score >= 0.5:
        return "Leaning Towards Buy"
    elif score <= -3.5:
        return "Strong Sell Candidate"
    elif score <= -1.5:
        return "Sell Candidate"
    elif score <= -0.5:
        return "Leaning Towards Sell"
    else:
        return "Neutral / Hold - Mixed Signals"


def get_real_news_headlines(query_term, company_name, num_headlines=5):
    print(f"[LOG] get_real_news_headlines: Fetching news for query='{query_term}', company='{company_name}'")
    if not NEWS_API_KEY:
        print("[LOG] get_real_news_headlines: NEWS_API_KEY is not configured. Returning placeholder.")
        return [{"title": "NewsAPI key not configured. News service unavailable.", "source": "System", "url": "#"}]

    search_query = company_name if company_name and company_name != query_term else f"{query_term} stock"
    if "Ltd" in search_query or "Limited" in search_query:
        search_query = search_query.replace(" Ltd", "").replace(" Limited", "")

    headlines_list = []
    api_urls_tried = []
    user_agent = {
        'User-Agent': f'ASXDashboardApp/1.0 (render.com; +{os.environ.get("RENDER_EXTERNAL_URL", "your-app-name.onrender.com")})'}

    url_intitle = (f"https://newsapi.org/v2/everything?"
                   f"qInTitle={requests.utils.quote(search_query)}"
                   f"&language=en&sortBy=publishedAt&pageSize={num_headlines}&apiKey={NEWS_API_KEY}")
    api_urls_tried.append(f"Attempt 1 (qInTitle): {url_intitle.replace(NEWS_API_KEY, 'REDACTED_KEY')}")

    try:
        response = requests.get(url_intitle, timeout=15, headers=user_agent)  # Increased timeout, added user-agent
        print(f"[LOG] get_real_news_headlines (qInTitle): Status {response.status_code} for {search_query}")
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

        if not headlines_list or len(headlines_list) < num_headlines // 2:
            print(
                f"[LOG] get_real_news_headlines: qInTitle returned {len(headlines_list)} results. Trying broader query.")
            url_broader = (f"https://newsapi.org/v2/everything?"
                           f"q={requests.utils.quote(search_query)}"
                           f"&language=en&sortBy=relevancy&pageSize={num_headlines}&apiKey={NEWS_API_KEY}")  # Changed sortBy to relevancy
            api_urls_tried.append(f"Attempt 2 (q broader): {url_broader.replace(NEWS_API_KEY, 'REDACTED_KEY')}")

            response_broader = requests.get(url_broader, timeout=15, headers=user_agent)
            print(
                f"[LOG] get_real_news_headlines (q broader): Status {response_broader.status_code} for {search_query}")
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
            print(f"[LOG] get_real_news_headlines: No headlines found for '{search_query}' after all attempts.")
            return [{"title": f"No recent headlines found for '{search_query}'.", "source": "NewsAPI", "url": "#"}]

        print(
            f"[LOG] get_real_news_headlines: Successfully fetched {len(headlines_list)} headlines for '{search_query}'.")
        return headlines_list

    except requests.exceptions.HTTPError as http_err:
        print(
            f"[ERROR] get_real_news_headlines: HTTP error for {search_query}. Status: {http_err.response.status_code}. Response: {http_err.response.text[:200]}...")  # Log part of response
        print(f"URLs tried: {api_urls_tried}")
        print(traceback.format_exc())
        return [{
                    "title": f"Could not fetch news (HTTP Error {http_err.response.status_code}). Please check API key or usage limits.",
                    "source": "System", "url": "#"}]
    except requests.exceptions.RequestException as e:
        print(
            f"[ERROR] get_real_news_headlines: RequestException for {search_query}. URLs tried: {api_urls_tried}. Error: {e}")
        print(traceback.format_exc())
        return [{"title": f"Could not fetch news. Error: {e}", "source": "System", "url": "#"}]
    except Exception as e:
        print(
            f"[ERROR] get_real_news_headlines: An unexpected error occurred while fetching news: {e}. URLs: {api_urls_tried}")
        print(traceback.format_exc())
        return [{"title": "An unexpected error occurred while fetching news.", "source": "System", "url": "#"}]


# --- Flask Routes ---
@app.route('/')
def index():
    example_tickers = ["CBA.AX", "BHP.AX", "NAB.AX", "AAPL", "GOOGL", "MSFT", "TSLA"]
    return render_template('index_analysis.html', tickers=example_tickers)


@app.route('/dashboard/<string:ticker_symbol>')
def dashboard(ticker_symbol):
    print(f"[LOG] dashboard: Request for ticker: {ticker_symbol}")
    stock_df = get_stock_data(ticker_symbol)

    if stock_df is None or stock_df.empty:
        print(f"[LOG] dashboard: stock_df is None or empty for {ticker_symbol}. Aborting with 404.")
        abort(404,
              description=f"Could not retrieve or process historical price data for ticker '{ticker_symbol}'. Check if the ticker is valid and has available data, or try again later.")

    stock_name = ticker_symbol.upper()
    current_price_val = "N/A"
    change_val = "N/A"
    change_percent_val = "N/A"
    yf_ticker_info = None

    print(f"[LOG] dashboard: Attempting to fetch yf.Ticker.info for {ticker_symbol}")
    try:
        # It's good practice to re-initialize Ticker object if info is needed and not already fetched
        # or if you want fresh .info data
        yf_ticker_obj = yf.Ticker(ticker_symbol)
        yf_ticker_info = yf_ticker_obj.info  # This can be slow or fail
        stock_name = yf_ticker_info.get('longName', yf_ticker_info.get('shortName', ticker_symbol.upper()))
        print(f"[LOG] dashboard: Successfully fetched .info for {ticker_symbol}. Name: {stock_name}")

        # Price data primarily from history_df as it's more reliable for 'Close'
        if not stock_df.empty and 'Close' in stock_df.columns and len(stock_df['Close']) > 0:
            current_price_val = stock_df["Close"].iloc[-1]
            prev_close = stock_df["Close"].iloc[-2] if len(
                stock_df["Close"]) > 1 else current_price_val  # Use current if only 1 day
            if isinstance(current_price_val, (int, float)) and isinstance(prev_close, (int, float)):
                change_val = current_price_val - prev_close
                change_percent_val = (change_val / prev_close) * 100 if prev_close != 0 else 0
        elif yf_ticker_info:  # Fallback to .info if history_df was problematic for current price
            print(f"[LOG] dashboard: Using .info for price as stock_df was insufficient for {ticker_symbol}")
            current_price_val = yf_ticker_info.get('currentPrice', yf_ticker_info.get('regularMarketPrice',
                                                                                      yf_ticker_info.get(
                                                                                          'regularMarketPreviousClose')))
            prev_close = yf_ticker_info.get('regularMarketPreviousClose',
                                            current_price_val)  # Fallback carefully for prev_close
            if isinstance(current_price_val, (int, float)) and isinstance(prev_close, (int, float)):
                change_val = current_price_val - prev_close
                change_percent_val = (change_val / prev_close) * 100 if prev_close != 0 else 0
            else:  # Ensure they are not None before math
                change_val, change_percent_val = "N/A", "N/A"

    except Exception as e:
        print(f"[ERROR] dashboard: Could not fetch full Ticker.info for {ticker_symbol}: {e}")
        print(traceback.format_exc())
        # Fallback using only historical data if .info failed, already handled for current_price_val from stock_df
        if not stock_df.empty and 'Close' in stock_df.columns and len(stock_df['Close']) > 0:
            current_price_val = stock_df["Close"].iloc[-1]  # Ensure it's set if info fails
            # Change calc would be as above if stock_df has >1 rows
        else:  # If both stock_df and .info fail for price
            print(f"[LOG] dashboard: Both stock_df and Ticker.info failed to provide price for {ticker_symbol}")
            current_price_val = "N/A"  # Already default, but explicit

    fundamentals = {
        "Market Cap": "N/A", "Trailing P/E": "N/A", "Forward P/E": "N/A", "PEG Ratio": "N/A",
        "Price to Sales (TTM)": "N/A", "Price to Book": "N/A", "Enterprise Value to EBITDA": "N/A",
        "Trailing EPS": "N/A", "Forward EPS": "N/A", "Dividend Yield": "N/A", "Beta": "N/A",
        "52 Week High": "N/A", "52 Week Low": "N/A", "Average Volume (10 day)": "N/A",
        "Profit Margins": "N/A", "Return on Equity (ROE)": "N/A"
    }
    if yf_ticker_info:
        print(f"[LOG] dashboard: Processing fundamentals from .info for {ticker_symbol}")
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
            if isinstance(val, (int, float)):
                fundamentals[key] = f"{prefix}{val * factor:.2f}{suffix}"
            elif val is None:
                fundamentals[key] = "N/A"  # Explicitly N/A if None

        avg_vol = yf_ticker_info.get('averageVolume10days', yf_ticker_info.get('averageVolume'))
        if isinstance(avg_vol, (int, float)): fundamentals["Average Volume (10 day)"] = f"{avg_vol:,.0f}"
    else:
        print(f"[LOG] dashboard: yf_ticker_info is None for {ticker_symbol}, fundamentals will be N/A.")

    print(f"[LOG] dashboard: Performing technical analyses for {ticker_symbol}")
    sma_analysis = analyze_sma(stock_df.copy() if stock_df is not None else None)  # Pass None if df is None
    rsi_analysis = analyze_rsi(stock_df.copy() if stock_df is not None else None)
    macd_analysis = analyze_macd(stock_df.copy() if stock_df is not None else None)
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
    print(f"[LOG] dashboard: Rendering dashboard_analysis.html for {ticker_symbol}")
    return render_template('dashboard_analysis.html', data=data)


@app.errorhandler(404)
def page_not_found(e):
    error_description = e.description if hasattr(e, 'description') else "The requested page was not found."
    print(f"[LOG] page_not_found: 404 error - {error_description}")
    return render_template('404.html', error_description=error_description), 404


# --- Debugging Routes ---
@app.route('/test-yfinance-minimal/<string:ticker_sym>')
def test_yfinance_minimal(ticker_sym):
    print(f"[LOG] test_yfinance_minimal: Request for ticker: {ticker_sym}")
    try:
        stock = yf.Ticker(ticker_sym)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)  # Fetch 1 month of data for test

        print(f"[LOG] test_yfinance_minimal: Getting history for {ticker_sym}")
        hist = stock.history(start=start_date, end=end_date, timeout=20)  # Added timeout

        result_message = ""
        if not hist.empty:
            result_message += f"Success for {ticker_sym}! Fetched {len(hist)} history rows. First row: {hist.iloc[0].to_dict()}\n"
        else:
            result_message += f"History data for {ticker_sym} was empty.\n"

        print(f"[LOG] test_yfinance_minimal: Getting .info for {ticker_sym}")
        info = stock.info  # This can be slow or fail
        if info and info.get('regularMarketPrice'):
            result_message += f".info found price: {info['regularMarketPrice']}. Sector: {info.get('sector', 'N/A')}"
        elif info:
            result_message += f".info fetched but no regularMarketPrice. Keys: {list(info.keys())[:10]}"
        else:
            result_message += ".info was empty or could not be fetched."

        print(f"[LOG] test_yfinance_minimal: Result for {ticker_sym}: {result_message}")
        return jsonify({"ticker": ticker_sym, "message": result_message, "status": "success"})

    except Exception as e:
        error_msg = f"Error during minimal yfinance test for {ticker_sym}: {str(e)}"
        print(f"[ERROR] test_yfinance_minimal: {error_msg}")
        print(traceback.format_exc())
        return jsonify(
            {"ticker": ticker_sym, "message": error_msg, "traceback": traceback.format_exc(), "status": "error"}), 500


@app.route('/debug-network')
def debug_network_connectivity():
    print("[LOG] debug_network_connectivity: Request received.")
    urls_to_test = {
        "Google DNS Ping (check general outbound)": "8.8.8.8",  # Ping target
        "Yahoo Finance Site": "https://finance.yahoo.com",
        "Yahoo Finance Query1 API": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d",
        # Example API endpoint
        "NewsAPI (if key is set)": f"https://newsapi.org/v2/everything?q=test&apiKey={NEWS_API_KEY if NEWS_API_KEY else 'NO_KEY_SET'}"
    }
    results = {}

    for name, url_or_ip in urls_to_test.items():
        print(f"[LOG] debug_network_connectivity: Testing '{name}' ({url_or_ip})")
        if "Ping" in name:  # Basic ping using subprocess
            # This might not work in all Render environments depending on permissions / installed tools
            try:
                import subprocess
                # Use -c 1 for a single ping, timeout 5 seconds
                process = subprocess.run(['ping', '-c', '1', '-W', '5', url_or_ip], capture_output=True, text=True,
                                         timeout=10)
                if process.returncode == 0:
                    results[name] = f"Ping to {url_or_ip} successful. Output: {process.stdout[:100]}..."
                else:
                    results[
                        name] = f"Ping to {url_or_ip} failed. Return code: {process.returncode}. Stderr: {process.stderr[:100]}..."
            except FileNotFoundError:
                results[name] = f"Ping command not found for {url_or_ip}. Cannot perform ping test."
            except subprocess.TimeoutExpired:
                results[name] = f"Ping to {url_or_ip} timed out."
            except Exception as e_ping:
                results[name] = f"Ping to {url_or_ip} error: {str(e_ping)}"
        else:  # HTTP GET request
            try:
                headers = {'User-Agent': 'RenderDebugConnectivityTest/1.0'}
                response = requests.get(url_or_ip, timeout=15, headers=headers)  # 15s timeout
                results[
                    name] = f"URL: {url_or_ip.replace(NEWS_API_KEY, 'REDACTED_KEY') if NEWS_API_KEY and NEWS_API_KEY in url_or_ip else url_or_ip} -> Status: {response.status_code}, Len: {len(response.content)}"
                if response.status_code != 200:
                    results[name] += f", Response Text (first 200 chars): {response.text[:200]}"

            except requests.exceptions.Timeout:
                results[name] = f"URL: {url_or_ip} -> TIMEOUT"
            except requests.exceptions.ConnectionError:
                results[name] = f"URL: {url_or_ip} -> CONNECTION ERROR"
            except Exception as e_req:
                results[name] = f"URL: {url_or_ip} -> Error: {str(e_req)}"
        print(f"[LOG] debug_network_connectivity: Result for '{name}': {results[name]}")
    return jsonify(results)


if __name__ == '__main__':
    # This block is for local development.
    # Render will use your Procfile (e.g., web: gunicorn app:app) or Start Command.
    print("Starting Flask app in debug mode for local development...")
    # The template and static file creation logic has been removed.
    # Ensure these files are in your Git repository.
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))