import { apiFetch } from './api.js?v=2.11';
import { authSuspended } from './auth.js?v=2.11';

export const SYMBOL_TO_TOKEN = {
  AAPL: 'NSE_EQ|INE062A01020',  // mapped to SBIN
  MSFT: 'NSE_EQ|INE160A01022',  // mapped to PNB
  TSLA: 'NSE_EQ|INE467I01027',  // mapped to TCS
  NVDA: 'NSE_EQ|INE009A01021',  // mapped to INFY
  AMZN: 'NSE_EQ|INE075A01022',  // mapped to WIPRO
  BTC: 'NSE_EQ|INE062A01020'    // custom scaled from SBIN
};

class MockMarketFeed {
  constructor() {
    this.prices = {
      AAPL: 194.20,
      MSFT: 348.50,
      NVDA: 462.10,
      TSLA: 238.80,
      AMZN: 130.40,
      BTC: 58500.00
    };
    this.listeners = [];
    this.intervalId = null;
    // Instrument keys added through the user's watchlist (GAP-9). The backend
    // subscribes them for streaming; the ticker polls the same set.
    this.extraKeys = [];
    this.keyPrices = {};
    this.startSimulation();
  }

  // Retrieve current prices
  getCurrentPrices() {
    return { ...this.prices };
  }

  // Latest LTP for a raw Upstox instrument key
  getKeyPrice(key) {
    return this.keyPrices[key];
  }

  // Replace the watchlist-derived instrument keys polled alongside the demo map
  setExtraKeys(keys) {
    this.extraKeys = Array.isArray(keys) ? [...new Set(keys)] : [];
  }

  // Subscribe to price changes
  subscribe(callback) {
    this.listeners.push(callback);
    // Return unsubscribe function
    return () => {
      this.listeners = this.listeners.filter(l => l !== callback);
    };
  }

  // Add a new custom ticker to the simulation if it doesn't exist
  addTicker(symbol, initialPrice = 100.0) {
    const sym = symbol.toUpperCase().trim();
    if (!this.prices[sym]) {
      this.prices[sym] = parseFloat(initialPrice) || 100.0;
      this.notifyListeners(sym, this.prices[sym], 0);
    }
  }

  // Start polling our FastAPI server for real-time prices
  startSimulation() {
    if (this.intervalId) return;

    const pollPrices = async () => {
      try {
        // Signed out after a 401: the gate owns the screen, keep the timer idle
        // instead of logging a rejected request every 2.5 s.
        if (authSuspended()) return;

        const tokensToPoll = Array.from(new Set([
          ...Object.values(SYMBOL_TO_TOKEN),
          ...this.extraKeys
        ])).join(',');

        const response = await apiFetch(`/api/prices?tokens=${encodeURIComponent(tokensToPoll)}`);
        const json = await response.json();
        
        if (json && json.data) {
          const liveData = json.data;
          this.keyPrices = { ...liveData };
          const updatedList = [];

          Object.keys(SYMBOL_TO_TOKEN).forEach(symbol => {
            const token = SYMBOL_TO_TOKEN[symbol];
            let newPrice = liveData[token];

            if (newPrice !== undefined) {
              // Custom scaling for Bitcoin to make it look realistic
              if (symbol === 'BTC') {
                newPrice = newPrice * 90.0;
              }

              const oldPrice = this.prices[symbol];
              if (oldPrice !== newPrice) {
                const percentChange = ((newPrice - oldPrice) / oldPrice) * 100;
                
                this.prices[symbol] = parseFloat(newPrice.toFixed(2));
                updatedList.push({
                  symbol: symbol,
                  price: this.prices[symbol],
                  change: percentChange
                });
              }
            }
          });

          if (updatedList.length > 0) {
            this.notifyBulkListeners(updatedList);
          }
        }
      } catch (err) {
        console.error("Failed to poll real-time prices from FastAPI:", err);
      }
    };

    // Run immediately on start, then poll every 2.5 seconds
    pollPrices();
    this.intervalId = setInterval(pollPrices, 2500);
  }

  stopSimulation() {
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  notifyListeners(symbol, price, change) {
    this.listeners.forEach(callback => {
      try {
        callback([{ symbol, price, change }]);
      } catch (e) {
        console.error("Error in price update listener:", e);
      }
    });
  }

  notifyBulkListeners(updates) {
    this.listeners.forEach(callback => {
      try {
        callback(updates);
      } catch (e) {
        console.error("Error in bulk price update listener:", e);
      }
    });
  }
}

export const marketFeed = new MockMarketFeed();
