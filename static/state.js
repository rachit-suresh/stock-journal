import { apiFetch } from './api.js';

// Writes are optimistic: the UI updates first and the server is told after.
// When that background write fails the change only exists in this browser, so
// say so instead of letting it look saved (app.js turns this into a toast).
function reportSyncFailure(what, error) {
  console.error(`Failed to sync ${what} with the backend:`, error);
  try {
    document.dispatchEvent(new CustomEvent('sj:sync-error', { detail: { what } }));
  } catch (e) {
    // No document (or no listener): the console line is the only record left.
  }
}

// A write only counts as saved when the server accepted it. A 4xx/5xx comes
// back as a normal Response, so it has to be turned into a rejection here or
// the optimistic UI would keep looking successful.
async function pushOrFail(path, options) {
  const response = await apiFetch(path, options);
  if (!response.ok) {
    throw new Error(`${options.method || 'GET'} ${path} returned ${response.status}`);
  }
  return response;
}

class StateManager {
  constructor() {
    this.trades = [];
    this.strategies = [];
    this.emotions = [];
    // No starting capital: the journal never invents cash you did not deposit
    // (SPEC-FE-5), so every valuation starts at ₹0.00 and only reflects
    // positions you actually record.
    this.onLoadCallback = null;
    this.loadState();
  }

  // Register a callback to update UI when async data is loaded
  onLoad(callback) {
    this.onLoadCallback = callback;
    // If data is already populated, fire it immediately
    if (this.trades.length > 0) {
      callback();
    }
  }

  // Load from FastAPI backend, fallback to LocalStorage/Mock if offline
  async loadState() {
    try {
      const response = await apiFetch('/api/journal');
      const json = await response.json();
      if (json.success && json.data) {
        this.trades = json.data.trades;
        this.strategies = json.data.strategies;
        this.emotions = json.data.emotions;
        
        // Notify listener (e.g. app.js) to re-render
        if (this.onLoadCallback) {
          this.onLoadCallback();
        }
        return;
      }
    } catch (e) {
      console.warn("Could not connect to FastAPI backend. Loading from LocalStorage fallback:", e);
    }

    // Offline / LocalStorage fallback
    try {
      const storedTrades = localStorage.getItem('stock_journal_trades');
      // No demo content: a new account starts with an empty journal.
      this.trades = storedTrades ? JSON.parse(storedTrades) : [];

      const storedStrats = localStorage.getItem('stock_journal_strategies');
      this.strategies = storedStrats ? JSON.parse(storedStrats) : ["Breakout", "Pullback Support", "Gap Fill", "Trend Continuation", "Mean Reversion"];

      const storedEmotions = localStorage.getItem('stock_journal_emotions');
      this.emotions = storedEmotions ? JSON.parse(storedEmotions) : ["Disciplined", "Confident", "Neutral", "Anxious", "FOMO", "Greedy"];
      
      if (this.onLoadCallback) {
        this.onLoadCallback();
      }
    } catch (e) {
      console.error("Failed to load local state fallback:", e);
      this.trades = [];
      this.strategies = ["Breakout", "Pullback Support", "Gap Fill", "Trend Continuation", "Mean Reversion"];
      this.emotions = ["Disciplined", "Confident", "Neutral", "Anxious", "FOMO", "Greedy"];
    }
  }

  // Background update helper
  async syncTrades(tradesList) {
    try {
      localStorage.setItem('stock_journal_trades', JSON.stringify(tradesList));
    } catch (e) {}
  }

  // --- STRATEGIES ---
  getStrategies() {
    return [...this.strategies];
  }

  addStrategy(name) {
    const cleanName = name.trim();
    if (!cleanName) return false;
    
    const exists = this.strategies.some(s => s.toLowerCase() === cleanName.toLowerCase());
    if (exists) return false;

    this.strategies.push(cleanName);
    
    // Asynchronous backend push
    pushOrFail('/api/strategies', {
      method: 'POST',
      body: JSON.stringify({ name: cleanName })
    }).catch(err => reportSyncFailure('strategy', err));

    try {
      localStorage.setItem('stock_journal_strategies', JSON.stringify(this.strategies));
    } catch(e){}

    return true;
  }

  deleteStrategy(name) {
    const index = this.strategies.findIndex(s => s.toLowerCase() === name.toLowerCase());
    if (index !== -1) {
      const actualName = this.strategies[index];
      this.strategies.splice(index, 1);
      
      // Asynchronous backend push
      pushOrFail(`/api/strategies/${encodeURIComponent(actualName)}`, {
        method: 'DELETE'
      }).catch(err => reportSyncFailure('strategy deletion', err));

      try {
        localStorage.setItem('stock_journal_strategies', JSON.stringify(this.strategies));
      } catch(e){}

      // Re-assign all trades using this strategy to 'Uncategorized'
      this.trades = this.trades.map(t => {
        if (t.strategy === actualName) {
          return { ...t, strategy: 'Uncategorized' };
        }
        return t;
      });
      this.syncTrades(this.trades);
      return true;
    }
    return false;
  }

  // --- EMOTIONS ---
  getEmotions() {
    return [...this.emotions];
  }

  addEmotion(name) {
    const cleanName = name.trim();
    if (!cleanName) return false;

    const exists = this.emotions.some(e => e.toLowerCase() === cleanName.toLowerCase());
    if (exists) return false;

    this.emotions.push(cleanName);

    // Asynchronous backend push
    pushOrFail('/api/emotions', {
      method: 'POST',
      body: JSON.stringify({ name: cleanName })
    }).catch(err => reportSyncFailure('emotion', err));

    try {
      localStorage.setItem('stock_journal_emotions', JSON.stringify(this.emotions));
    } catch(e){}

    return true;
  }

  deleteEmotion(name) {
    const index = this.emotions.findIndex(e => e.toLowerCase() === name.toLowerCase());
    if (index !== -1) {
      const actualName = this.emotions[index];
      this.emotions.splice(index, 1);

      // Asynchronous backend push
      pushOrFail(`/api/emotions/${encodeURIComponent(actualName)}`, {
        method: 'DELETE'
      }).catch(err => reportSyncFailure('emotion deletion', err));

      try {
        localStorage.setItem('stock_journal_emotions', JSON.stringify(this.emotions));
      } catch(e){}

      // Re-assign all trades using this emotion to 'Neutral'
      this.trades = this.trades.map(t => {
        if (t.emotion === actualName) {
          return { ...t, emotion: 'Neutral' };
        }
        return t;
      });
      this.syncTrades(this.trades);
      return true;
    }
    return false;
  }

  // --- TRADES CRUD ---
  getTrades(descending = true) {
    return [...this.trades].sort((a, b) => {
      const dateA = new Date(a.date).getTime();
      const dateB = new Date(b.date).getTime();
      return descending ? dateB - dateA : dateA - dateB;
    });
  }

  addTrade(tradeData) {
    const tempId = 'trade_temp_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5);
    const newTrade = {
      id: tempId,
      symbol: tradeData.symbol.toUpperCase().trim(),
      instrumentKey: tradeData.instrumentKey
        ? String(tradeData.instrumentKey).trim().toUpperCase()
        : null,
      side: tradeData.side,
      price: parseFloat(tradeData.price),
      stopLoss: tradeData.stopLoss ? parseFloat(tradeData.stopLoss) : null,
      pfMatrix: tradeData.pfMatrix !== undefined && tradeData.pfMatrix !== '' && tradeData.pfMatrix !== null ? parseFloat(tradeData.pfMatrix) : null,
      rsMatrix: tradeData.rsMatrix !== undefined && tradeData.rsMatrix !== '' && tradeData.rsMatrix !== null ? parseFloat(tradeData.rsMatrix) : null,
      xPercentage: tradeData.xPercentage !== undefined && tradeData.xPercentage !== '' && tradeData.xPercentage !== null ? parseFloat(tradeData.xPercentage) : null,
      shares: parseInt(tradeData.shares, 10),
      date: tradeData.date || new Date().toISOString(),
      strategy: tradeData.strategy || 'Uncategorized',
      emotion: tradeData.emotion || 'Neutral',
      mistakes: Array.isArray(tradeData.mistakes) ? tradeData.mistakes : ['None'],
      notes: tradeData.notes || ''
    };
    
    // Add locally immediately for snappy UI
    this.trades.push(newTrade);
    this.syncTrades(this.trades);

    // Asynchronous backend sync
    pushOrFail('/api/trades', {
      method: 'POST',
      body: JSON.stringify(newTrade)
    })
    .then(res => res.json())
    .then(json => {
      if (json.success && json.data) {
        // Swap temp ID with server generated ID
        const idx = this.trades.findIndex(t => t.id === tempId);
        if (idx !== -1) {
          this.trades[idx].id = json.data.id;
          this.syncTrades(this.trades);
        }
      }
    })
    .catch(err => reportSyncFailure('trade', err));

    return newTrade;
  }

  editTrade(id, updatedFields) {
    const index = this.trades.findIndex(t => t.id === id);
    if (index === -1) return null;

    const existing = this.trades[index];
    const updated = {
      ...existing,
      ...updatedFields,
      symbol: updatedFields.symbol ? updatedFields.symbol.toUpperCase().trim() : existing.symbol,
      instrumentKey: updatedFields.instrumentKey !== undefined
        ? (String(updatedFields.instrumentKey || '').trim().toUpperCase() || null)
        : (existing.instrumentKey || null),
      price: updatedFields.price ? parseFloat(updatedFields.price) : existing.price,
      stopLoss: updatedFields.stopLoss ? parseFloat(updatedFields.stopLoss) : null,
      pfMatrix: updatedFields.pfMatrix !== undefined && updatedFields.pfMatrix !== '' && updatedFields.pfMatrix !== null ? parseFloat(updatedFields.pfMatrix) : null,
      rsMatrix: updatedFields.rsMatrix !== undefined && updatedFields.rsMatrix !== '' && updatedFields.rsMatrix !== null ? parseFloat(updatedFields.rsMatrix) : null,
      xPercentage: updatedFields.xPercentage !== undefined && updatedFields.xPercentage !== '' && updatedFields.xPercentage !== null ? parseFloat(updatedFields.xPercentage) : null,
      shares: updatedFields.shares ? parseInt(updatedFields.shares, 10) : existing.shares,
    };

    // Update locally
    this.trades[index] = updated;
    this.syncTrades(this.trades);

    // Empty optional inputs mean "clear this field" (SPEC-PER-5), so they are
    // sent as explicit nulls instead of "" — an empty string fails validation.
    const toNullableNumber = (v) => (v === '' || v === null || v === undefined ? null : parseFloat(v));
    const payload = {
      ...updatedFields,
      stopLoss: toNullableNumber(updatedFields.stopLoss),
      pfMatrix: toNullableNumber(updatedFields.pfMatrix),
      rsMatrix: toNullableNumber(updatedFields.rsMatrix),
      xPercentage: toNullableNumber(updatedFields.xPercentage),
    };

    // Asynchronous backend edit
    pushOrFail(`/api/trades/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(payload)
    }).catch(err => reportSyncFailure('edit', err));

    return updated;
  }

  deleteTrade(id) {
    const index = this.trades.findIndex(t => t.id === id);
    if (index !== -1) {
      this.trades.splice(index, 1);
      this.syncTrades(this.trades);

      // Asynchronous backend deletion
      pushOrFail(`/api/trades/${encodeURIComponent(id)}`, {
        method: 'DELETE'
      }).catch(err => reportSyncFailure('deletion', err));

      return true;
    }
    return false;
  }

  // --- IMPORT / EXPORT ---
  exportData() {
    return JSON.stringify({
      version: "1.3",
      strategies: this.strategies,
      emotions: this.emotions,
      trades: this.trades
    }, null, 2);
  }

  importData(jsonString) {
    try {
      const data = JSON.parse(jsonString);
      if (data && Array.isArray(data.trades)) {
        this.trades = data.trades;
        // Exports up to format 1.2 carried a `startingBalance`; it is ignored
        // now that there is no invented capital to apply it to.
        if (Array.isArray(data.strategies)) {
          this.strategies = data.strategies;
        }
        if (Array.isArray(data.emotions)) {
          this.emotions = data.emotions;
        }
        
        this.syncTrades(this.trades);
        
        // Push full state to backend
        pushOrFail('/api/journal/import', {
          method: 'POST',
          body: JSON.stringify(data)
        }).catch(err => reportSyncFailure('import', err));

        return true;
      }
    } catch (e) {
      console.error("Import parsing failed:", e);
    }
    return false;
  }

  // --- PORTFOLIO CALCULATION ENGINE ---
  // Symbol -> instrument key for the live feed. The latest trade for a symbol
  // wins, so editing a trade's key re-points its live price.
  getSymbolKeys() {
    const map = {};
    [...this.trades]
      .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
      .forEach(t => {
        if (t.symbol && t.instrumentKey) map[t.symbol] = t.instrumentKey;
      });
    return map;
  }

  getMetrics(currentPrices = {}) {
    const chronologicalTrades = [...this.trades].sort((a, b) => {
      return new Date(a.date).getTime() - new Date(b.date).getTime();
    });

    const positions = {};
    let runningRealizedPnL = 0;
    // Cumulative *realized* P&L, starting at zero: with no invented starting
    // capital this series is a P&L, not an account balance (SPEC-FE-5).
    const equityCurve = [{
      date: 'Start',
      pnl: 0
    }];

    const closedTradePnLs = [];

    const initGroupStat = () => ({
      pnl: 0,
      count: 0,
      wins: 0,
      pfMatrixSum: 0,
      pfMatrixCount: 0,
      rsMatrixSum: 0,
      rsMatrixCount: 0,
      xPercentageSum: 0,
      xPercentageCount: 0
    });

    const strategyAnalysis = {};
    const emotionAnalysis = {};

    chronologicalTrades.forEach(trade => {
      const { symbol, side, price, shares, strategy, emotion } = trade;
      const isBuy = side === 'BUY';
      const deltaShares = isBuy ? shares : -shares;

      if (!positions[symbol]) {
        positions[symbol] = {
          shares: 0,
          avgCost: 0,
          realizedPnL: 0
        };
      }

      const pos = positions[symbol];
      const prevShares = pos.shares;
      const newShares = prevShares + deltaShares;

      let tradeRealizedPnL = 0;

      if (prevShares === 0) {
        pos.avgCost = price;
        pos.shares = newShares;
      } else if (Math.sign(prevShares) === Math.sign(deltaShares)) {
        pos.avgCost = (Math.abs(prevShares) * pos.avgCost + shares * price) / Math.abs(newShares);
        pos.shares = newShares;
      } else {
        const closedShares = Math.min(Math.abs(prevShares), Math.abs(deltaShares));
        const sign = Math.sign(prevShares);
        const pnlFactor = sign > 0 ? 1 : -1;
        tradeRealizedPnL = (price - pos.avgCost) * closedShares * pnlFactor;
        
        pos.realizedPnL += tradeRealizedPnL;
        runningRealizedPnL += tradeRealizedPnL;
        closedTradePnLs.push({
          tradeId: trade.id,
          symbol,
          pnl: tradeRealizedPnL,
          strategy,
          emotion,
          date: trade.date
        });

        if (strategy) {
          if (!strategyAnalysis[strategy]) strategyAnalysis[strategy] = initGroupStat();
          const sStat = strategyAnalysis[strategy];
          sStat.pnl += tradeRealizedPnL;
          sStat.count++;
          if (tradeRealizedPnL > 0) sStat.wins++;
          
          if (trade.pfMatrix !== null && trade.pfMatrix !== undefined && !isNaN(trade.pfMatrix)) {
            sStat.pfMatrixSum += parseFloat(trade.pfMatrix);
            sStat.pfMatrixCount++;
          }
          if (trade.rsMatrix !== null && trade.rsMatrix !== undefined && !isNaN(trade.rsMatrix)) {
            sStat.rsMatrixSum += parseFloat(trade.rsMatrix);
            sStat.rsMatrixCount++;
          }
          if (trade.xPercentage !== null && trade.xPercentage !== undefined && !isNaN(trade.xPercentage)) {
            sStat.xPercentageSum += parseFloat(trade.xPercentage);
            sStat.xPercentageCount++;
          }
        }
        
        if (emotion) {
          if (!emotionAnalysis[emotion]) emotionAnalysis[emotion] = initGroupStat();
          const eStat = emotionAnalysis[emotion];
          eStat.pnl += tradeRealizedPnL;
          eStat.count++;
          if (tradeRealizedPnL > 0) eStat.wins++;

          if (trade.pfMatrix !== null && trade.pfMatrix !== undefined && !isNaN(trade.pfMatrix)) {
            eStat.pfMatrixSum += parseFloat(trade.pfMatrix);
            eStat.pfMatrixCount++;
          }
          if (trade.rsMatrix !== null && trade.rsMatrix !== undefined && !isNaN(trade.rsMatrix)) {
            eStat.rsMatrixSum += parseFloat(trade.rsMatrix);
            eStat.rsMatrixCount++;
          }
          if (trade.xPercentage !== null && trade.xPercentage !== undefined && !isNaN(trade.xPercentage)) {
            eStat.xPercentageSum += parseFloat(trade.xPercentage);
            eStat.xPercentageCount++;
          }
        }

        if (Math.abs(prevShares) > Math.abs(deltaShares)) {
          pos.shares = newShares;
        } else {
          const remainingShares = newShares;
          pos.shares = remainingShares;
          pos.avgCost = remainingShares !== 0 ? price : 0;
        }
      }

      equityCurve.push({
        date: new Date(trade.date).toLocaleDateString(),
        pnl: runningRealizedPnL
      });
    });

    let totalUnrealizedPnL = 0;
    // What the open book is worth right now: shares x price. A position with
    // no quote holds its cost basis and is counted, so the card can say so
    // instead of silently treating cost as market value.
    let totalPortfolioValue = 0;
    let unpricedValueCount = 0;
    const activePositions = [];

    Object.keys(positions).forEach(symbol => {
      const pos = positions[symbol];
      if (pos.shares !== 0) {
        // A position with no live quote must not borrow its own average cost:
        // that reports a flat ₹0.00 P&L, which reads as "the market has not
        // moved" instead of "we do not know". Keep it at cost and say so.
        const quote = currentPrices[symbol];
        const priced = typeof quote === 'number' && Number.isFinite(quote) && quote > 0;
        const curPrice = priced ? quote : pos.avgCost;
        let unrealizedPnL = 0;
        
        if (pos.shares > 0) {
          unrealizedPnL = (curPrice - pos.avgCost) * pos.shares;
        } else {
          unrealizedPnL = (pos.avgCost - curPrice) * Math.abs(pos.shares);
        }

        totalUnrealizedPnL += unrealizedPnL;
        if (!priced) unpricedValueCount += 1;
        totalPortfolioValue += Math.abs(pos.shares) * curPrice;
        activePositions.push({
          symbol,
          shares: pos.shares,
          avgCost: pos.avgCost,
          currentPrice: curPrice,
          priced,
          unrealizedPnL,
          marketValue: Math.abs(pos.shares) * curPrice
        });
      }
    });

    Object.keys(strategyAnalysis).forEach(strat => {
      const stat = strategyAnalysis[strat];
      stat.avgPfMatrix = stat.pfMatrixCount > 0 ? stat.pfMatrixSum / stat.pfMatrixCount : null;
      stat.avgRsMatrix = stat.rsMatrixCount > 0 ? stat.rsMatrixSum / stat.rsMatrixCount : null;
      stat.avgXPercentage = stat.xPercentageCount > 0 ? stat.xPercentageSum / stat.xPercentageCount : null;
    });

    Object.keys(emotionAnalysis).forEach(emo => {
      const stat = emotionAnalysis[emo];
      stat.avgPfMatrix = stat.pfMatrixCount > 0 ? stat.pfMatrixSum / stat.pfMatrixCount : null;
      stat.avgRsMatrix = stat.rsMatrixCount > 0 ? stat.rsMatrixSum / stat.rsMatrixCount : null;
      stat.avgXPercentage = stat.xPercentageCount > 0 ? stat.xPercentageSum / stat.xPercentageCount : null;
    });

    const winningTrades = closedTradePnLs.filter(t => t.pnl > 0);
    const losingTrades = closedTradePnLs.filter(t => t.pnl < 0);
    const flatTrades = closedTradePnLs.filter(t => t.pnl === 0);

    const winCount = winningTrades.length;
    const lossCount = losingTrades.length;
    const totalClosedCount = closedTradePnLs.length;

    const winRate = totalClosedCount > 0 ? (winCount / totalClosedCount) * 100 : 0;

    const grossProfit = winningTrades.reduce((sum, t) => sum + t.pnl, 0);
    const grossLoss = Math.abs(losingTrades.reduce((sum, t) => sum + t.pnl, 0));
    
    const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : (grossProfit > 0 ? Infinity : 1);
    
    const avgWin = winCount > 0 ? grossProfit / winCount : 0;
    const avgLoss = lossCount > 0 ? grossLoss / lossCount : 0;

    const totalRealizedPnL = runningRealizedPnL;

    return {
      portfolioValue: totalPortfolioValue,
      unpricedValueCount,
      totalRealizedPnL,
      totalUnrealizedPnL,
      netPnL: totalRealizedPnL + totalUnrealizedPnL,
      winRate,
      profitFactor,
      avgWin,
      avgLoss,
      totalClosedCount,
      winCount,
      lossCount,
      flatTradesCount: flatTrades.length,
      activePositions,
      equityCurve,
      closedTradePnLs,
      strategyAnalysis,
      emotionAnalysis
    };
  }
}

export const stateManager = new StateManager();
