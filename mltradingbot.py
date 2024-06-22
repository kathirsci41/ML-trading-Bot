from dotenv import load_dotenv
import os
import logging
from lumibot.brokers import Alpaca
from lumibot.strategies.strategy import Strategy
from datetime import datetime, timedelta
import yfinance as yf
import time

# Load environment variables from .env file
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API Credentials - Use environment variables for security
API_KEY = os.getenv('ALPACA_API_KEY')
API_SECRET = os.getenv('ALPACA_API_SECRET')

# Ensure API credentials are available
if not API_KEY or not API_SECRET:
    raise ValueError("API Key and Secret must be set as environment variables.")

ALPACA_CREDS = {
    "API_KEY": API_KEY,
    "API_SECRET": API_SECRET,
    "PAPER": True  # Set to True for paper trading environment
}

# Create Alpaca broker instance
alpaca_broker = Alpaca(ALPACA_CREDS)

class MLTrader(Strategy):
    def initialize(self, symbol: str = "SPY", cash_at_risk: float = 0.5):
        """Initialize the trading strategy."""
        self.symbol = symbol
        self.last_trade = None
        self.cash_at_risk = cash_at_risk

    def get_cash(self):
        try:
            account = self.broker.get_account()
            return float(account['cash'])
        except Exception as e:
            logger.error(f"Error getting cash: {e}")
            return 0

    def get_last_price(self, symbol: str):
        try:
            bars = self.broker.get_bars(symbol, "minute", limit=1)
            return bars[0].c
        except Exception as e:
            logger.error(f"Error getting last price: {e}")
            return 0

    def get_datetime(self):
        return datetime.now()

    def get_dates(self):
        """Get today's date and the date three days prior."""
        today = self.get_datetime()
        three_days_prior = today - timedelta(days=3)
        return today.strftime('%Y-%m-%d'), three_days_prior.strftime('%Y-%m-%d')

    def get_sentiment(self):
        """Estimate the sentiment of recent news headlines."""
        try:
            today, three_days_prior = self.get_dates()
            news = self.broker.get_news(symbol=self.symbol, start=three_days_prior, end=today)
            news_headlines = [ev.headline for ev in news]
            probability, sentiment = estimate_sentiment(news_headlines)
            return probability, sentiment
        except Exception as e:
            logger.error(f"Error fetching sentiment: {e}")
            return 0, "neutral"  # Default to neutral sentiment on error

    def position_sizing(self):
        """Calculate the position size based on available cash and risk."""
        cash = self.get_cash()
        last_price = self.get_last_price(self.symbol)
        if last_price == 0:
            return cash, 0, 0
        quantity = round(cash * self.cash_at_risk / last_price, 0)
        return cash, last_price, quantity

    def sell_all(self):
        try:
            positions = self.broker.list_positions()
            for position in positions:
                self.broker.submit_order(
                    symbol=position.symbol,
                    qty=position.qty,
                    side='sell',
                    type='market',
                    time_in_force='gtc'
                )
        except Exception as e:
            logger.error(f"Error selling all positions: {e}")

    def create_order(self, symbol, quantity, side, type, take_profit_price, stop_loss_price):
        order = {
            'symbol': symbol,
            'qty': quantity,
            'side': side,
            'type': type,
            'time_in_force': 'gtc',
            'order_class': 'bracket',
            'take_profit': {
                'limit_price': take_profit_price,
            },
            'stop_loss': {
                'stop_price': stop_loss_price,
            }
        }
        return order

    def submit_order(self, order):
        try:
            self.broker.submit_order(**order)
        except Exception as e:
            logger.error(f"Error submitting order: {e}")

    def on_trading_iteration(self):
        """Execute trading logic based on sentiment analysis."""
        try:
            cash, last_price, quantity = self.position_sizing()
            probability, sentiment = self.get_sentiment()

            if cash > last_price and last_price != 0:
                if sentiment == "positive" and probability > 0.999:
                    if self.last_trade == "sell":
                        self.sell_all()
                    order = self.create_order(
                        self.symbol,
                        quantity,
                        "buy",
                        type="bracket",
                        take_profit_price=last_price * 1.20,
                        stop_loss_price=last_price * 0.95
                    )
                    self.submit_order(order)
                    self.last_trade = "buy"
                elif sentiment == "negative" and probability > 0:
                    if self.last_trade == "buy":
                        self.sell_all()
                    self.last_trade = "sell"
        except Exception as e:
            logger.error(f"Error in trading iteration: {e}")

# Instantiate the strategy
strategy = MLTrader(broker=alpaca_broker)

# Initialize the strategy with parameters
strategy.initialize(symbol="SPY", cash_at_risk=0.5)

# Run the strategy in a loop (this is a simple example, you might want to use a more robust scheduling method)
while True:
    strategy.on_trading_iteration()
    time.sleep(86400)  # Sleep for 24 hours (86400 seconds)
