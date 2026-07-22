const SYMBOL_TO_TOKEN = {
  AAPL: '3045',  // mapped to SBIN
  MSFT: '2885',  // mapped to PNB
  TSLA: '11536', // mapped to TCS
  NVDA: '1594',  // mapped to INFY
  AMZN: '3456',  // mapped to WIPRO
  BTC: '3045'    // custom scaled from SBIN
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
    this.startSimulation();
  }

  // Retrieve current prices
  getCurrentPrices() {
    return { ...this.prices };
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

    const tokensToPoll = Array.from(new Set(Object.values(SYMBOL_TO_TOKEN))).join(',');

    const pollPrices = async () => {
      try {
        const baseUrl = window.FASTAPI_URL || window.API_BASE_URL || '';
        const response = await fetch(`${baseUrl}/api/prices?tokens=${tokensToPoll}`);
        const json = await response.json();
        
        if (json && json.data) {
          const liveData = json.data;
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
