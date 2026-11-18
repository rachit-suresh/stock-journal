import { apiFetch } from './api.js';
import { authSuspended } from './auth.js';

/**
 * Live price feed for one account.
 *
 * There is no built-in symbol list: the feed polls exactly the instrument keys
 * this account asked for (watchlist) plus the keys attached to its trades, so a
 * new account starts with an empty, honest feed. `prices` is keyed by the trade
 * symbol so the position maths works unchanged; `keyPrices` keeps the raw keys
 * for watchlist rows.
 */
class MarketFeed {
  constructor() {
    this.prices = {};
    this.keyPrices = {};
    this.symbolKeys = {};
    this.extraKeys = [];
    this.listeners = [];
    this.intervalId = null;
    // Feed health, so the header badge can stop claiming "LIVE" while the
    // backend has no ticks (market closed, token rejected, socket silent).
    this.live = null; // null until the first poll answers
    this.lastTickAt = null;
    this.feedError = null;
    this.statusListeners = [];
    this.startPolling();
  }

  getCurrentPrices() {
    return { ...this.prices };
  }

  // Latest LTP for a raw Upstox instrument key
  getKeyPrice(key) {
    return this.keyPrices[key];
  }

  // Keys added through the user's watchlist (GAP-9); the backend subscribes
  // them for streaming and the poller asks for the same set.
  setExtraKeys(keys) {
    this.extraKeys = Array.isArray(keys) ? [...new Set(keys)] : [];
  }

  // symbol -> instrument key, taken from the journal, so a position can show a
  // live price instead of its average cost.
  setSymbolKeys(map) {
    this.symbolKeys = map && typeof map === 'object' ? { ...map } : {};
  }

  polledKeys() {
    return [...new Set([...this.extraKeys, ...Object.values(this.symbolKeys)])];
  }

  subscribe(callback) {
    this.listeners.push(callback);
    return () => {
      this.listeners = this.listeners.filter(l => l !== callback);
    };
  }

  /** Feed health as `{live, lastTickAt, error}`; fires on every change. */
  onStatus(callback) {
    this.statusListeners.push(callback);
    if (this.live !== null || this.feedError) callback(this.getStatus());
    return () => {
      this.statusListeners = this.statusListeners.filter(l => l !== callback);
    };
  }

  getStatus() {
    return { live: this.live === true, lastTickAt: this.lastTickAt, error: this.feedError };
  }

  setStatus(live, lastTickAt, error = null) {
    if (live === this.live && lastTickAt === this.lastTickAt && error === this.feedError) return;
    this.live = live;
    this.lastTickAt = lastTickAt;
    this.feedError = error;
    const status = this.getStatus();
    this.statusListeners.forEach(callback => {
      try {
        callback(status);
      } catch (e) {
        console.error('Error in feed status listener:', e);
      }
    });
  }

  startPolling() {
    if (this.intervalId) return;

    const pollPrices = async () => {
      // Signed out after a 401: the gate owns the screen, keep the timer idle
      // instead of logging a rejected request every 2.5 s.
      if (authSuspended()) return;

      const keys = this.polledKeys();
      if (keys.length === 0) {
        // Nothing to ask for. The endpoint would answer with placeholders, so
        // stay idle and let the badge say we are waiting for instrument keys.
        this.keyPrices = {};
        this.setStatus(false, this.lastTickAt);
        this.notifyBulkListeners([]);
        return;
      }

      try {
        const response = await apiFetch(`/api/prices?tokens=${encodeURIComponent(keys.join(','))}`);
        const json = await response.json();
        const meta = (json && json.meta) || {};
        const liveData = (json && json.data) || {};

        this.keyPrices = { ...liveData };

        const updatedList = [];
        Object.entries(this.symbolKeys).forEach(([symbol, key]) => {
          const entry = meta[key];
          // A key the backend has never ticked comes back as the 100.0
          // placeholder; painting it would invent a price.
          if (!entry || entry.as_of === null) return;

          const raw = liveData[key];
          if (raw === undefined || raw === null) return;

          const price = parseFloat(Number(raw).toFixed(2));
          const previous = this.prices[symbol];
          if (previous === price) return;

          this.prices[symbol] = price;
          updatedList.push({
            symbol,
            price,
            change: previous ? ((price - previous) / previous) * 100 : 0
          });
        });

        // Fire even with an empty list: watchlist rows refresh off this tick.
        this.notifyBulkListeners(updatedList);

        // meta carries one entry per key the poll asked for, so the newest
        // `as_of` and any `stale: false` together describe the whole feed.
        const stamps = Object.values(meta)
          .map(entry => (entry && entry.as_of) || null)
          .filter(Boolean);
        const fresh = Object.values(meta).some(entry => entry && entry.stale === false);
        this.setStatus(fresh, stamps.length ? Math.max(...stamps) : this.lastTickAt);
      } catch (err) {
        console.error('Failed to poll real-time prices from FastAPI:', err);
        this.setStatus(false, this.lastTickAt, err?.message || String(err));
      }
    };

    // Run immediately on start, then poll every 2.5 seconds
    pollPrices();
    this.intervalId = setInterval(pollPrices, 2500);
  }

  notifyBulkListeners(updates) {
    this.listeners.forEach(callback => {
      try {
        callback(updates);
      } catch (e) {
        console.error('Error in bulk price update listener:', e);
      }
    });
  }
}

export const marketFeed = new MarketFeed();
