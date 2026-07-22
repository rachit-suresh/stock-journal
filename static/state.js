import { initialTrades } from './mockData.js?v=2.3';

class StateManager {
  constructor() {
    this.trades = [];
    this.strategies = [];
    this.emotions = [];
    this.startingBalance = 100000;
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
      const response = await fetch('/api/journal');
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
      this.trades = storedTrades ? JSON.parse(storedTrades) : [...initialTrades];

      const storedStrats = localStorage.getItem('stock_journal_strategies');
      this.strategies = storedStrats ? JSON.parse(storedStrats) : ["Breakout", "Pullback Support", "Gap Fill", "Trend Continuation", "Mean Reversion"];

      const storedEmotions = localStorage.getItem('stock_journal_emotions');
      this.emotions = storedEmotions ? JSON.parse(storedEmotions) : ["Disciplined", "Confident", "Neutral", "Anxious", "FOMO", "Greedy"];
      
      if (this.onLoadCallback) {
        this.onLoadCallback();
      }
    } catch (e) {
      console.error("Failed to load local state fallback:", e);
      this.trades = [...initialTrades];
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
    fetch('/api/journal?type=strategy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: cleanName })
    }).catch(err => console.error("Failed to sync new strategy with backend:", err));

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
      fetch(`/api/journal?type=strategy&name=${actualName}`, {
        method: 'DELETE'
      }).catch(err => console.error("Failed to sync strategy deletion with backend:", err));

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
    fetch('/api/journal?type=emotion', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: cleanName })
    }).catch(err => console.error("Failed to sync emotion with backend:", err));

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
      fetch(`/api/journal?type=emotion&name=${actualName}`, {
        method: 'DELETE'
      }).catch(err => console.error("Failed to sync emotion deletion with backend:", err));

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
    fetch('/api/journal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(tradeData)
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
    .catch(err => console.error("Failed to save trade to backend:", err));

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

    // Asynchronous backend edit
    fetch(`/api/journal?id=${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updatedFields)
    }).catch(err => console.error("Failed to sync edited trade with backend:", err));

    return updated;
  }

  deleteTrade(id) {
    const index = this.trades.findIndex(t => t.id === id);
    if (index !== -1) {
      this.trades.splice(index, 1);
      this.syncTrades(this.trades);

      // Asynchronous backend deletion
      fetch(`/api/journal?id=${id}`, {
        method: 'DELETE'
      }).catch(err => console.error("Failed to delete trade from backend:", err));

      return true;
    }
    return false;
  }

  // --- IMPORT / EXPORT ---
  exportData() {
    return JSON.stringify({
      version: "1.2",
      startingBalance: this.startingBalance,
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
        if (data.startingBalance) {
          this.startingBalance = parseFloat(data.startingBalance);
        }
        if (Array.isArray(data.strategies)) {
          this.strategies = data.strategies;
        }
        if (Array.isArray(data.emotions)) {
          this.emotions = data.emotions;
        }
        
        this.syncTrades(this.trades);
        
        // Push full state to backend
        fetch('/api/journal?action=import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        }).catch(err => console.error("Failed to sync imported data to backend:", err));

        return true;
      }
    } catch (e) {
      console.error("Import parsing failed:", e);
    }
    return false;
  }

  resetToMock() {
    this.trades = [...initialTrades];
    this.strategies = ["Breakout", "Pullback Support", "Gap Fill", "Trend Continuation", "Mean Reversion"];
    this.emotions = ["Disciplined", "Confident", "Neutral", "Anxious", "FOMO", "Greedy"];
    
    this.syncTrades(this.trades);

    // Call reset on backend
    fetch('/api/journal?action=reset', {
      method: 'POST'
    }).catch(err => console.error("Failed to sync database reset to backend:", err));
  }

  clearAll() {
    this.trades = [];
    this.syncTrades(this.trades);
    
    fetch('/api/journal?action=import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trades: [], strategies: this.strategies, emotions: this.emotions })
    }).catch(err => console.error("Failed to clear backend database:", err));
  }

  // --- PORTFOLIO CALCULATION ENGINE ---
  getMetrics(currentPrices = {}) {
    const chronologicalTrades = [...this.trades].sort((a, b) => {
      return new Date(a.date).getTime() - new Date(b.date).getTime();
    });

    const positions = {};
    let runningRealizedPnL = 0;
    const equityCurve = [{
      date: 'Start',
      balance: this.startingBalance,
      realizedPnL: 0
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
        balance: this.startingBalance + runningRealizedPnL,
        realizedPnL: runningRealizedPnL
      });
    });

    let totalUnrealizedPnL = 0;
    const activePositions = [];

    Object.keys(positions).forEach(symbol => {
      const pos = positions[symbol];
      if (pos.shares !== 0) {
        const curPrice = currentPrices[symbol] || pos.avgCost;
        let unrealizedPnL = 0;
        
        if (pos.shares > 0) {
          unrealizedPnL = (curPrice - pos.avgCost) * pos.shares;
        } else {
          unrealizedPnL = (pos.avgCost - curPrice) * Math.abs(pos.shares);
        }

        totalUnrealizedPnL += unrealizedPnL;
        activePositions.push({
          symbol,
          shares: pos.shares,
          avgCost: pos.avgCost,
          currentPrice: curPrice,
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
    const accountEquity = this.startingBalance + totalRealizedPnL + totalUnrealizedPnL;

    return {
      startingBalance: this.startingBalance,
      accountEquity,
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
