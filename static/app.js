import { stateManager } from './state.js?v=2.3';
import { marketFeed } from './mockApi.js?v=2.3';

// ==========================================================================
// SECURITY & SANITIZATION HELPERS
// ==========================================================================
function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ==========================================================================
// APPLICATION STATE & DOM REFERENCES
// ==========================================================================
let currentPrices = marketFeed.getCurrentPrices();
let selectedMistakes = new Set();
let currentView = 'dashboard';

// Chart Instances
let equityChart = null;
let allocationChart = null;

// DOM Selections
const pageTitle = document.getElementById('page-title');
const navItems = document.querySelectorAll('.nav-item');
const pageViews = document.querySelectorAll('.page-view');

// Modal Elements - Add/Edit Trade
const modalTrade = document.getElementById('modal-trade');
const modalTradeClose = document.getElementById('modal-trade-close');
const btnAddTradeTrigger = document.getElementById('btn-add-trade-trigger');
const btnFormCancel = document.getElementById('btn-form-cancel');
const tradeForm = document.getElementById('trade-form');
const formTradeId = document.getElementById('form-trade-id');
const modalTitle = document.getElementById('modal-title');
const btnFormSubmit = document.getElementById('btn-form-submit');
const mistakePills = document.querySelectorAll('#mistakes-pills .pill-option');

// Modal Elements - Trade Details
const modalTradeDetail = document.getElementById('modal-trade-detail');
const modalDetailClose = document.getElementById('modal-detail-close');
const btnDetailClose = document.getElementById('btn-detail-close');
const btnDetailDelete = document.getElementById('btn-detail-delete');
const btnDetailEdit = document.getElementById('btn-detail-edit');
let currentlyViewingTradeId = null;

// Strategy Manager Elements
const strategyAddForm = document.getElementById('strategy-add-form');
const strategyNewName = document.getElementById('strategy-new-name');
const strategiesListTbody = document.getElementById('strategies-list-tbody');

// Emotions Manager Elements
const emotionAddForm = document.getElementById('emotion-add-form');
const emotionNewName = document.getElementById('emotion-new-name');
const emotionsListTbody = document.getElementById('emotions-list-tbody');

// Trade Log Filters
const filterSearch = document.getElementById('filter-search');
const filterSide = document.getElementById('filter-side');
const filterStrategy = document.getElementById('filter-strategy');
const filterEmotion = document.getElementById('filter-emotion');
const filterCount = document.getElementById('filter-count');
const tradesTableBody = document.getElementById('trades-table-body');

// Import / Export
const btnExport = document.getElementById('btn-export');
const btnImport = document.getElementById('btn-import');
const fileImportInput = document.getElementById('file-import-input');
const btnResetMock = document.getElementById('btn-reset-mock');

// Metric Elements
const metricEquity = document.getElementById('metric-equity');
const metricRealizedPnL = document.getElementById('metric-realized-pnl');
const metricUnrealizedPnL = document.getElementById('metric-unrealized-pnl');
const metricWinRate = document.getElementById('metric-winrate');
const metricProfitFactor = document.getElementById('metric-profit-factor');
const metricWinLossCount = document.getElementById('metric-win-loss-count');

// Container Elements
const positionsContainer = document.getElementById('positions-container');
const watchlistContainer = document.getElementById('watchlist-container');

// Toast Container
const toastContainer = document.getElementById('toast-container');

// ==========================================================================
// TOAST NOTIFICATIONS
// ==========================================================================
function showToast(message, type = 'success') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span>${escapeHtml(message)}</span>
  `;
  toastContainer.appendChild(toast);

  // Trigger Slide In
  setTimeout(() => {
    toast.style.transform = 'translateX(0)';
  }, 10);

  // Remove toast after 3 seconds
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => {
      toast.remove();
    }, 300);
  }, 3000);
}

// ==========================================================================
// CHART INITIALIZATION & UPDATES
// ==========================================================================
function initCharts(equityData = [], allocationData = []) {
  const equityCtx = document.getElementById('equityChart').getContext('2d');
  
  const purpleGradient = equityCtx.createLinearGradient(0, 0, 0, 300);
  purpleGradient.addColorStop(0, 'rgba(139, 92, 246, 0.4)');
  purpleGradient.addColorStop(1, 'rgba(139, 92, 246, 0.0)');

  const chartLabels = equityData.map(d => d.date);
  const chartBalances = equityData.map(d => d.balance);

  if (equityChart) equityChart.destroy();
  equityChart = new Chart(equityCtx, {
    type: 'line',
    data: {
      labels: chartLabels,
      datasets: [{
        label: 'Account Equity ($)',
        data: chartBalances,
        borderColor: '#8b5cf6',
        borderWidth: 3,
        backgroundColor: purpleGradient,
        fill: true,
        tension: 0.3,
        pointBackgroundColor: '#8b5cf6',
        pointBorderColor: '#ffffff',
        pointRadius: 4,
        pointHoverRadius: 6
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'index',
          intersect: false,
          backgroundColor: '#111625',
          titleColor: '#9ca3af',
          bodyColor: '#f3f4f6',
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 1,
          callbacks: {
            label: function(context) {
              return ` Equity: $${context.parsed.y.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: '#6b7280', font: { family: 'Outfit' } }
        },
        y: {
          grid: { color: 'rgba(255, 255, 255, 0.03)' },
          ticks: { 
            color: '#6b7280', 
            font: { family: 'Outfit' },
            callback: value => '$' + value.toLocaleString()
          }
        }
      }
    }
  });

  const allocCtx = document.getElementById('allocationChart').getContext('2d');
  
  const allocLabels = allocationData.map(d => d.symbol);
  const allocValues = allocationData.map(d => d.marketValue);

  if (allocationChart) allocationChart.destroy();

  if (allocLabels.length === 0) {
    allocationChart = new Chart(allocCtx, {
      type: 'doughnut',
      data: {
        labels: ['No Active Positions'],
        datasets: [{
          data: [100],
          backgroundColor: ['rgba(255, 255, 255, 0.05)'],
          borderWidth: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { color: '#9ca3af', font: { family: 'Outfit', size: 12 } }
          }
        }
      }
    });
  } else {
    allocationChart = new Chart(allocCtx, {
      type: 'doughnut',
      data: {
        labels: allocLabels,
        datasets: [{
          data: allocValues,
          backgroundColor: [
            '#8b5cf6', // Purple
            '#3b82f6', // Blue
            '#10b981', // Emerald
            '#f59e0b', // Amber
            '#ec4899', // Pink
            '#14b8a6'  // Teal
          ],
          borderColor: '#111625',
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { color: '#9ca3af', font: { family: 'Outfit', size: 12 } }
          },
          tooltip: {
            backgroundColor: '#111625',
            callbacks: {
              label: function(context) {
                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                const val = context.parsed;
                const pct = ((val / total) * 100).toFixed(1);
                return ` ${context.label}: $${val.toLocaleString()} (${pct}%)`;
              }
            }
          }
        }
      }
    });
  }
}

// ==========================================================================
// RENDER VIEWS & CONTROLS
// ==========================================================================

const formatCurrency = (val) => {
  if (val === null || val === undefined || isNaN(val)) return '-';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD'
  }).format(val);
};

// Render Watchlist Panel
function renderWatchlist() {
  watchlistContainer.innerHTML = '';
  
  const watchlistTickers = [
    { symbol: 'AAPL', name: 'Apple Inc.' },
    { symbol: 'MSFT', name: 'Microsoft Corp.' },
    { symbol: 'NVDA', name: 'NVIDIA Corp.' },
    { symbol: 'TSLA', name: 'Tesla Inc.' },
    { symbol: 'AMZN', name: 'Amazon.com Inc.' },
    { symbol: 'BTC', name: 'Bitcoin (USD)' }
  ];

  watchlistTickers.forEach(ticker => {
    const price = currentPrices[ticker.symbol] || 0;
    
    const item = document.createElement('div');
    item.className = 'watchlist-item';
    item.id = `watchlist-${ticker.symbol}`;
    item.innerHTML = `
      <div class="ticker-name-box">
        <span class="ticker-symbol">${escapeHtml(ticker.symbol)}</span>
        <span class="ticker-company">${escapeHtml(ticker.name)}</span>
      </div>
      <div class="ticker-pricing">
        <div class="ticker-price" id="price-tick-${ticker.symbol}">${formatCurrency(price)}</div>
      </div>
    `;
    watchlistContainer.appendChild(item);
  });
}

// Render Dashboard View
function renderDashboardView(metrics) {
  metricEquity.textContent = formatCurrency(metrics.accountEquity);
  
  metricRealizedPnL.textContent = formatCurrency(metrics.totalRealizedPnL);
  metricRealizedPnL.className = `metric-val ${metrics.totalRealizedPnL > 0 ? 'text-up' : metrics.totalRealizedPnL < 0 ? 'text-down' : ''}`;
  metricProfitFactor.textContent = `Profit Factor: ${metrics.profitFactor === Infinity ? '∞' : metrics.profitFactor.toFixed(2)}`;

  metricUnrealizedPnL.textContent = formatCurrency(metrics.totalUnrealizedPnL);
  metricUnrealizedPnL.className = `metric-val ${metrics.totalUnrealizedPnL > 0 ? 'text-up' : metrics.totalUnrealizedPnL < 0 ? 'text-down' : ''}`;

  metricWinRate.textContent = `${metrics.winRate.toFixed(1)}%`;
  metricWinLossCount.textContent = `${metrics.winCount} wins / ${metrics.lossCount} losses`;

  positionsContainer.innerHTML = '';
  if (metrics.activePositions.length === 0) {
    positionsContainer.innerHTML = `<div class="text-neutral" style="text-align: center; padding: 20px;">No active positions. Add trades to open.</div>`;
  } else {
    metrics.activePositions.forEach(pos => {
      const isLong = pos.shares > 0;
      const pnlClass = pos.unrealizedPnL > 0 ? 'text-up' : pos.unrealizedPnL < 0 ? 'text-down' : '';
      const item = document.createElement('div');
      item.className = 'position-item';
      item.innerHTML = `
        <div class="pos-details">
          <span class="pos-symbol">
            ${escapeHtml(pos.symbol)}
            <span class="pos-side-badge ${isLong ? 'badge-buy' : 'badge-sell'}">${isLong ? 'LONG' : 'SHORT'}</span>
          </span>
          <span class="pos-shares-cost">${Math.abs(pos.shares)} shares @ avg cost ${formatCurrency(pos.avgCost)}</span>
        </div>
        <div class="pos-pnl">
          <div class="pos-pnl-val ${pnlClass}">${formatCurrency(pos.unrealizedPnL)}</div>
          <div class="pos-pnl-pct ${pnlClass}">${pos.unrealizedPnL > 0 ? '+' : ''}${((pos.unrealizedPnL / (Math.abs(pos.shares) * pos.avgCost)) * 100).toFixed(2)}%</div>
        </div>
      `;
      positionsContainer.appendChild(item);
    });
  }

  initCharts(metrics.equityCurve, metrics.activePositions);
}

// Populate Strategy selectors dynamically
function populateStrategySelectors() {
  const currentStrategies = stateManager.getStrategies();
  
  // 1. Modal Select
  const modalStrategySelect = document.getElementById('form-strategy');
  modalStrategySelect.innerHTML = '';
  currentStrategies.forEach(strat => {
    modalStrategySelect.innerHTML += `<option value="${escapeHtml(strat)}">${escapeHtml(strat)}</option>`;
  });
  modalStrategySelect.innerHTML += `<option value="Uncategorized">Uncategorized</option>`;
  modalStrategySelect.innerHTML += `<option value="__custom__">+ Add Custom Strategy...</option>`;

  // 2. Table Filter Select
  const currentFilterVal = filterStrategy.value;
  filterStrategy.innerHTML = '<option value="">All Strategies</option>';
  currentStrategies.forEach(strat => {
    filterStrategy.innerHTML += `<option value="${escapeHtml(strat)}">${escapeHtml(strat)}</option>`;
  });
  filterStrategy.innerHTML += `<option value="Uncategorized">Uncategorized</option>`;
  filterStrategy.value = currentFilterVal;
}

// Populate Emotion selectors dynamically
function populateEmotionSelectors() {
  const currentEmotions = stateManager.getEmotions();

  // 1. Modal Select
  const modalEmotionSelect = document.getElementById('form-emotion');
  modalEmotionSelect.innerHTML = '';
  currentEmotions.forEach(emo => {
    modalEmotionSelect.innerHTML += `<option value="${escapeHtml(emo)}">${escapeHtml(emo)}</option>`;
  });
  modalEmotionSelect.innerHTML += `<option value="Neutral">Neutral</option>`;
  modalEmotionSelect.innerHTML += `<option value="__custom__">+ Add Custom Emotion...</option>`;

  // 2. Table Filter Select
  const currentFilterVal = filterEmotion.value;
  filterEmotion.innerHTML = '<option value="">All Emotions</option>';
  currentEmotions.forEach(emo => {
    filterEmotion.innerHTML += `<option value="${escapeHtml(emo)}">${escapeHtml(emo)}</option>`;
  });
  filterEmotion.innerHTML += `<option value="Neutral">Neutral</option>`;
  filterEmotion.value = currentFilterVal;
}

// Render Trade Log View
function renderTradeLogView() {
  const trades = stateManager.getTrades(true);
  
  // Refresh selector lists
  populateStrategySelectors();
  populateEmotionSelectors();

  // Gather filter inputs
  const searchQuery = filterSearch.value.toUpperCase().trim();
  const sideQuery = filterSide.value;
  const stratQuery = filterStrategy.value;
  const emoQuery = filterEmotion.value;

  const filteredTrades = trades.filter(trade => {
    const matchesSearch = !searchQuery || trade.symbol.includes(searchQuery);
    const matchesSide = !sideQuery || trade.side === sideQuery;
    const matchesStrat = !stratQuery || trade.strategy === stratQuery;
    const matchesEmo = !emoQuery || trade.emotion === emoQuery;
    return matchesSearch && matchesSide && matchesStrat && matchesEmo;
  });

  filterCount.textContent = `Showing ${filteredTrades.length} of ${trades.length} entries`;

  tradesTableBody.innerHTML = '';
  if (filteredTrades.length === 0) {
    tradesTableBody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 30px;">No trades matched the filters.</td></tr>`;
    return;
  }

  filteredTrades.forEach(trade => {
    const dateObj = new Date(trade.date);
    const formattedDate = dateObj.toLocaleDateString() + ' ' + dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const sideClass = trade.side === 'BUY' ? 'badge-buy' : 'badge-sell';
    const totalValue = trade.price * trade.shares;

    const tr = document.createElement('tr');
    tr.className = 'clickable-row';
    tr.setAttribute('data-id', trade.id);
    tr.innerHTML = `
      <td>${formattedDate}</td>
      <td style="font-weight: 700;">${escapeHtml(trade.symbol)}</td>
      <td><span class="badge ${sideClass}">${trade.side}</span></td>
      <td class="td-mono">${formatCurrency(trade.price)}</td>
      <td class="td-mono">${formatCurrency(trade.stopLoss)}</td>
      <td class="td-mono">${trade.shares}</td>
      <td class="td-mono">${formatCurrency(totalValue)}</td>
      <td><span class="badge badge-strategy">${escapeHtml(trade.strategy || 'Uncategorized')}</span></td>
      <td><span class="badge badge-emotion">${escapeHtml(trade.emotion || 'Neutral')}</span></td>
      <td>
        <div style="display: flex; gap: 8px;">
          <button class="btn btn-secondary btn-sm btn-edit-trade" data-id="${trade.id}" style="padding: 4px 8px;">Edit</button>
          <button class="btn btn-danger-outline btn-sm btn-delete-trade" data-id="${trade.id}" style="padding: 4px 8px;">Delete</button>
        </div>
      </td>
    `;
    tradesTableBody.appendChild(tr);
  });

  // Attach click listener to row details trigger
  document.querySelectorAll('.clickable-row').forEach(row => {
    row.addEventListener('click', (e) => {
      if (e.target.closest('.btn-edit-trade') || e.target.closest('.btn-delete-trade')) {
        return;
      }
      const id = row.getAttribute('data-id');
      openTradeDetailModal(id);
    });
  });

  // Attach edit/delete button triggers directly
  document.querySelectorAll('.btn-edit-trade').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const tradeId = btn.getAttribute('data-id');
      openEditTradeModal(tradeId);
    });
  });

  document.querySelectorAll('.btn-delete-trade').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const tradeId = btn.getAttribute('data-id');
      if (confirm("Are you sure you want to delete this trade entry?")) {
        const deleted = stateManager.deleteTrade(tradeId);
        if (deleted) {
          showToast("Trade log entry deleted successfully.", "danger");
          updateAllViews();
        }
      }
    });
  });
}

// Render Strategies Management View
function renderStrategiesView() {
  const currentStrategies = stateManager.getStrategies();
  const trades = stateManager.getTrades(false);

  const stratCounts = {};
  trades.forEach(t => {
    const s = t.strategy || 'Uncategorized';
    stratCounts[s] = (stratCounts[s] || 0) + 1;
  });

  strategiesListTbody.innerHTML = '';
  
  if (currentStrategies.length === 0) {
    strategiesListTbody.innerHTML = `<tr><td colspan="2" style="text-align: center; color: var(--text-muted); padding: 20px;">No custom strategies created yet.</td></tr>`;
    return;
  }

  currentStrategies.forEach(strat => {
    const count = stratCounts[strat] || 0;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="font-weight: 600;">
        <span class="badge badge-strategy" style="font-size: 13px;">${escapeHtml(strat)}</span>
        <span style="font-size: 12px; color: var(--text-muted); margin-left: 10px;">(${count} trades in log)</span>
      </td>
      <td style="text-align: right;">
        <button class="btn btn-danger-outline btn-sm btn-delete-strategy" data-name="${escapeHtml(strat)}">
          Delete
        </button>
      </td>
    `;
    strategiesListTbody.appendChild(tr);
  });

  document.querySelectorAll('.btn-delete-strategy').forEach(btn => {
    btn.addEventListener('click', () => {
      const name = btn.getAttribute('data-name');
      if (confirm(`Are you sure you want to delete the strategy setup "${name}"?\nAny existing trades using this strategy will revert to 'Uncategorized'.`)) {
        const deleted = stateManager.deleteStrategy(name);
        if (deleted) {
          showToast(`Deleted strategy: ${name}`, 'danger');
          updateAllViews();
        }
      }
    });
  });
}

// Render Emotions Management View
function renderEmotionsView() {
  const currentEmotions = stateManager.getEmotions();
  const trades = stateManager.getTrades(false);

  const emoCounts = {};
  trades.forEach(t => {
    const e = t.emotion || 'Neutral';
    emoCounts[e] = (emoCounts[e] || 0) + 1;
  });

  emotionsListTbody.innerHTML = '';

  if (currentEmotions.length === 0) {
    emotionsListTbody.innerHTML = `<tr><td colspan="2" style="text-align: center; color: var(--text-muted); padding: 20px;">No custom emotions created yet.</td></tr>`;
    return;
  }

  currentEmotions.forEach(emo => {
    const count = emoCounts[emo] || 0;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="font-weight: 600;">
        <span class="badge badge-emotion" style="font-size: 13px;">${escapeHtml(emo)}</span>
        <span style="font-size: 12px; color: var(--text-muted); margin-left: 10px;">(${count} trades in log)</span>
      </td>
      <td style="text-align: right;">
        <button class="btn btn-danger-outline btn-sm btn-delete-emotion" data-name="${escapeHtml(emo)}">
          Delete
        </button>
      </td>
    `;
    emotionsListTbody.appendChild(tr);
  });

  document.querySelectorAll('.btn-delete-emotion').forEach(btn => {
    btn.addEventListener('click', () => {
      const name = btn.getAttribute('data-name');
      if (confirm(`Are you sure you want to delete the emotion tag "${name}"?\nAny existing trades using this emotion will revert to 'Neutral'.`)) {
        const deleted = stateManager.deleteEmotion(name);
        if (deleted) {
          showToast(`Deleted emotion: ${name}`, 'danger');
          updateAllViews();
        }
      }
    });
  });
}

// Render Analytics View
function renderAnalyticsView(metrics) {
  document.getElementById('analytics-profit-factor').textContent = metrics.profitFactor === Infinity ? '∞' : metrics.profitFactor.toFixed(2);
  document.getElementById('analytics-avg-win').textContent = formatCurrency(metrics.avgWin);
  document.getElementById('analytics-avg-loss').textContent = formatCurrency(metrics.avgLoss);
  document.getElementById('analytics-trade-count').textContent = metrics.totalClosedCount;
  document.getElementById('analytics-winrate-pct').textContent = `Win Rate: ${metrics.winRate.toFixed(1)}%`;

  // Render Strategy performance breakdown
  const strategyTbody = document.getElementById('analytics-strategy-tbody');
  strategyTbody.innerHTML = '';
  const stratKeys = Object.keys(metrics.strategyAnalysis);
  if (stratKeys.length === 0) {
    strategyTbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 15px;">No strategy history yet.</td></tr>`;
  } else {
    stratKeys.forEach(strat => {
      const data = metrics.strategyAnalysis[strat];
      const wr = data.count > 0 ? (data.wins / data.count) * 100 : 0;
      const profitClass = data.pnl > 0 ? 'text-up' : data.pnl < 0 ? 'text-down' : '';
      
      const avgPf = (data.avgPfMatrix !== null && data.avgPfMatrix !== undefined) ? data.avgPfMatrix.toFixed(2) : '-';
      const avgRs = (data.avgRsMatrix !== null && data.avgRsMatrix !== undefined) ? data.avgRsMatrix.toFixed(2) : '-';
      const avgXpct = (data.avgXPercentage !== null && data.avgXPercentage !== undefined) ? `${data.avgXPercentage.toFixed(2)}%` : '-';

      strategyTbody.innerHTML += `
        <tr>
          <td><span class="badge badge-strategy">${escapeHtml(strat)}</span></td>
          <td>${data.count}</td>
          <td>${wr.toFixed(1)}%</td>
          <td class="td-mono ${profitClass}">${data.pnl > 0 ? '+' : ''}${formatCurrency(data.pnl)}</td>
          <td class="td-mono">${avgPf}</td>
          <td class="td-mono">${avgRs}</td>
          <td class="td-mono">${avgXpct}</td>
        </tr>
      `;
    });
  }

  // Render Emotion performance breakdown
  const emotionTbody = document.getElementById('analytics-emotion-tbody');
  emotionTbody.innerHTML = '';
  const emoKeys = Object.keys(metrics.emotionAnalysis);
  if (emoKeys.length === 0) {
    emotionTbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 15px;">No emotion history yet.</td></tr>`;
  } else {
    emoKeys.forEach(emo => {
      const data = metrics.emotionAnalysis[emo];
      const wr = data.count > 0 ? (data.wins / data.count) * 100 : 0;
      const profitClass = data.pnl > 0 ? 'text-up' : data.pnl < 0 ? 'text-down' : '';
      
      const avgPf = (data.avgPfMatrix !== null && data.avgPfMatrix !== undefined) ? data.avgPfMatrix.toFixed(2) : '-';
      const avgRs = (data.avgRsMatrix !== null && data.avgRsMatrix !== undefined) ? data.avgRsMatrix.toFixed(2) : '-';
      const avgXpct = (data.avgXPercentage !== null && data.avgXPercentage !== undefined) ? `${data.avgXPercentage.toFixed(2)}%` : '-';

      emotionTbody.innerHTML += `
        <tr>
          <td><span class="badge badge-emotion">${escapeHtml(emo)}</span></td>
          <td>${data.count}</td>
          <td>${wr.toFixed(1)}%</td>
          <td class="td-mono ${profitClass}">${data.pnl > 0 ? '+' : ''}${formatCurrency(data.pnl)}</td>
          <td class="td-mono">${avgPf}</td>
          <td class="td-mono">${avgRs}</td>
          <td class="td-mono">${avgXpct}</td>
        </tr>
      `;
    });
  }
}

// Master view update orchestrator
function updateAllViews() {
  const metrics = stateManager.getMetrics(currentPrices);
  
  if (currentView === 'dashboard') {
    renderDashboardView(metrics);
  } else if (currentView === 'tradelog') {
    renderTradeLogView();
  } else if (currentView === 'strategies') {
    renderStrategiesView();
  } else if (currentView === 'emotions') {
    renderEmotionsView();
  } else if (currentView === 'analytics') {
    renderAnalyticsView(metrics);
  }
}

// ==========================================================================
// MODAL: ADD / EDIT TRADE
// ==========================================================================
function openAddTradeModal() {
  modalTitle.textContent = "Record Trade";
  btnFormSubmit.textContent = "Save Entry";
  formTradeId.value = '';
  tradeForm.reset();
  
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  document.getElementById('form-date').value = now.toISOString().slice(0, 16);

  document.getElementById('form-stoploss').value = '';
  document.getElementById('form-pfmatrix').value = '';
  document.getElementById('form-rsmatrix').value = '';
  document.getElementById('form-xpct').value = '';
  
  document.getElementById('form-strategy-custom').value = '';
  document.getElementById('form-strategy-custom').style.display = 'none';
  document.getElementById('form-strategy-custom').removeAttribute('required');

  document.getElementById('form-emotion-custom').value = '';
  document.getElementById('form-emotion-custom').style.display = 'none';
  document.getElementById('form-emotion-custom').removeAttribute('required');

  selectedMistakes.clear();
  selectedMistakes.add("None");
  updateMistakePillsUI();

  populateStrategySelectors();
  populateEmotionSelectors();

  modalTrade.classList.add('active');
}

function openEditTradeModal(tradeId) {
  const trades = stateManager.getTrades(false);
  const trade = trades.find(t => t.id === tradeId);
  
  if (!trade) return;

  modalTitle.textContent = "Edit Trade Entry";
  btnFormSubmit.textContent = "Update Entry";
  formTradeId.value = trade.id;
  
  document.getElementById('form-symbol').value = trade.symbol;
  document.getElementById('form-side').value = trade.side;
  document.getElementById('form-price').value = trade.price;
  document.getElementById('form-shares').value = trade.shares;
  document.getElementById('form-notes').value = trade.notes;

  document.getElementById('form-stoploss').value = trade.stopLoss !== null ? trade.stopLoss : '';
  document.getElementById('form-pfmatrix').value = trade.pfMatrix !== null ? trade.pfMatrix : '';
  document.getElementById('form-rsmatrix').value = trade.rsMatrix !== null ? trade.rsMatrix : '';
  document.getElementById('form-xpct').value = trade.xPercentage !== null ? trade.xPercentage : '';
  
  document.getElementById('form-strategy-custom').value = '';
  document.getElementById('form-strategy-custom').style.display = 'none';
  document.getElementById('form-strategy-custom').removeAttribute('required');

  document.getElementById('form-emotion-custom').value = '';
  document.getElementById('form-emotion-custom').style.display = 'none';
  document.getElementById('form-emotion-custom').removeAttribute('required');

  if (trade.date) {
    const d = new Date(trade.date);
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    document.getElementById('form-date').value = d.toISOString().slice(0, 16);
  }

  selectedMistakes.clear();
  if (trade.mistakes && trade.mistakes.length > 0) {
    trade.mistakes.forEach(m => selectedMistakes.add(m));
  } else {
    selectedMistakes.add("None");
  }
  updateMistakePillsUI();

  populateStrategySelectors();
  populateEmotionSelectors();
  
  document.getElementById('form-strategy').value = trade.strategy || 'Uncategorized';
  document.getElementById('form-emotion').value = trade.emotion || 'Neutral';

  modalTrade.classList.add('active');
}

function closeTradeModal() {
  modalTrade.classList.remove('active');
  tradeForm.reset();
}

function updateMistakePillsUI() {
  mistakePills.forEach(pill => {
    const val = pill.getAttribute('data-value');
    if (selectedMistakes.has(val)) {
      pill.classList.add('selected');
    } else {
      pill.classList.remove('selected');
    }
  });
}

// ==========================================================================
// MODAL: TRADE DETAILS VIEW
// ==========================================================================
function openTradeDetailModal(tradeId) {
  const trades = stateManager.getTrades(false);
  const trade = trades.find(t => t.id === tradeId);
  
  if (!trade) return;

  currentlyViewingTradeId = tradeId;

  const dateObj = new Date(trade.date);
  const formattedDate = dateObj.toLocaleDateString() + ' ' + dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const sideClass = trade.side === 'BUY' ? 'badge-buy' : 'badge-sell';
  const totalValue = trade.price * trade.shares;

  // Use textContent directly for dynamic trade strings - safe by default
  document.getElementById('detail-date').textContent = formattedDate;
  document.getElementById('detail-symbol').textContent = trade.symbol;
  
  const sideBadge = document.getElementById('detail-side');
  sideBadge.textContent = trade.side;
  sideBadge.className = `badge ${sideClass}`;

  document.getElementById('detail-price').textContent = formatCurrency(trade.price);
  document.getElementById('detail-stoploss').textContent = formatCurrency(trade.stopLoss);
  document.getElementById('detail-shares').textContent = trade.shares;
  document.getElementById('detail-value').textContent = formatCurrency(totalValue);
  
  const stratBadge = document.getElementById('detail-strategy');
  stratBadge.textContent = trade.strategy || 'Uncategorized';
  
  const emoBadge = document.getElementById('detail-emotion');
  emoBadge.textContent = trade.emotion || 'Neutral';

  document.getElementById('detail-pfmatrix').textContent = (trade.pfMatrix !== null && trade.pfMatrix !== undefined) ? trade.pfMatrix.toFixed(2) : '-';
  document.getElementById('detail-rsmatrix').textContent = (trade.rsMatrix !== null && trade.rsMatrix !== undefined) ? trade.rsMatrix.toFixed(2) : '-';
  document.getElementById('detail-xpct').textContent = (trade.xPercentage !== null && trade.xPercentage !== undefined) ? `${trade.xPercentage.toFixed(2)}%` : '-';

  const mistakesContainer = document.getElementById('detail-mistakes');
  mistakesContainer.innerHTML = '';
  if (trade.mistakes && trade.mistakes.length > 0 && trade.mistakes[0] !== 'None') {
    trade.mistakes.forEach(m => {
      mistakesContainer.innerHTML += `<span class="tag-mistake">${escapeHtml(m)}</span>`;
    });
  } else {
    mistakesContainer.innerHTML = '<span class="tag-mistake tag-mistake-none">None</span>';
  }

  const notesContainer = document.getElementById('detail-notes');
  notesContainer.textContent = trade.notes || 'No journal log notes recorded for this trade.';

  modalTradeDetail.classList.add('active');
}

function closeTradeDetailModal() {
  modalTradeDetail.classList.remove('active');
  currentlyViewingTradeId = null;
}

// ==========================================================================
// PRICE Ticker & SIMULATOR SUBSCRIPTION
// ==========================================================================
function startMarketTickerSubscription() {
  marketFeed.subscribe(updates => {
    updates.forEach(upd => {
      currentPrices[upd.symbol] = upd.price;

      if (currentView === 'dashboard') {
        const tickEl = document.getElementById(`price-tick-${upd.symbol}`);
        if (tickEl) {
          tickEl.textContent = formatCurrency(upd.price);
          
          const flashClass = upd.change >= 0 ? 'price-up' : 'price-down';
          tickEl.classList.remove('price-up', 'price-down');
          tickEl.classList.add(flashClass);
          
          setTimeout(() => {
            tickEl.classList.remove('price-up', 'price-down');
          }, 800);
        }
      }
    });

    const metrics = stateManager.getMetrics(currentPrices);
    
    if (currentView === 'dashboard') {
      metricUnrealizedPnL.textContent = formatCurrency(metrics.totalUnrealizedPnL);
      metricUnrealizedPnL.className = `metric-val ${metrics.totalUnrealizedPnL > 0 ? 'text-up' : metrics.totalUnrealizedPnL < 0 ? 'text-down' : ''}`;
      metricEquity.textContent = formatCurrency(metrics.accountEquity);
      
      renderDashboardView(metrics);
    }
  });
}

// ==========================================================================
// EVENT ATTACHMENTS & INITIALIZATION
// ==========================================================================
document.addEventListener('DOMContentLoaded', () => {
  
  // Navigation Routing Switcher
  navItems.forEach(item => {
    item.addEventListener('click', () => {
      navItems.forEach(i => i.classList.remove('active'));
      item.classList.add('active');
      
      const targetView = item.getAttribute('data-view');
      currentView = targetView;
      
      pageViews.forEach(v => v.classList.remove('active'));
      document.getElementById(`view-${targetView}`).classList.add('active');
      
      if (targetView === 'dashboard') pageTitle.textContent = "Dashboard";
      if (targetView === 'tradelog') pageTitle.textContent = "Trade Log";
      if (targetView === 'strategies') pageTitle.textContent = "Manage Strategies";
      if (targetView === 'emotions') pageTitle.textContent = "Manage Emotions";
      if (targetView === 'analytics') pageTitle.textContent = "Analytics";

      updateAllViews();
    });
  });

  // Modal triggers
  btnAddTradeTrigger.addEventListener('click', openAddTradeModal);
  modalTradeClose.addEventListener('click', closeTradeModal);
  btnFormCancel.addEventListener('click', closeTradeModal);

  modalDetailClose.addEventListener('click', closeTradeDetailModal);
  btnDetailClose.addEventListener('click', closeTradeDetailModal);

  btnDetailDelete.addEventListener('click', () => {
    if (currentlyViewingTradeId && confirm("Are you sure you want to delete this trade?")) {
      const deleted = stateManager.deleteTrade(currentlyViewingTradeId);
      if (deleted) {
        showToast("Trade log entry deleted.", "danger");
        closeTradeDetailModal();
        updateAllViews();
      }
    }
  });

  btnDetailEdit.addEventListener('click', () => {
    if (currentlyViewingTradeId) {
      const tradeId = currentlyViewingTradeId;
      closeTradeDetailModal();
      openEditTradeModal(tradeId);
    }
  });

  // Custom strategy inline selector toggling
  const formStrategySelect = document.getElementById('form-strategy');
  const formStrategyCustom = document.getElementById('form-strategy-custom');
  formStrategySelect.addEventListener('change', () => {
    if (formStrategySelect.value === '__custom__') {
      formStrategyCustom.style.display = 'block';
      formStrategyCustom.setAttribute('required', 'true');
      formStrategyCustom.focus();
    } else {
      formStrategyCustom.style.display = 'none';
      formStrategyCustom.removeAttribute('required');
    }
  });

  // Custom emotion inline selector toggling
  const formEmotionSelect = document.getElementById('form-emotion');
  const formEmotionCustom = document.getElementById('form-emotion-custom');
  formEmotionSelect.addEventListener('change', () => {
    if (formEmotionSelect.value === '__custom__') {
      formEmotionCustom.style.display = 'block';
      formEmotionCustom.setAttribute('required', 'true');
      formEmotionCustom.focus();
    } else {
      formEmotionCustom.style.display = 'none';
      formEmotionCustom.removeAttribute('required');
    }
  });

  // Mistakes selection
  mistakePills.forEach(pill => {
    pill.addEventListener('click', () => {
      const val = pill.getAttribute('data-value');
      if (val === 'None') {
        selectedMistakes.clear();
        selectedMistakes.add('None');
      } else {
        selectedMistakes.delete('None');
        if (selectedMistakes.has(val)) {
          selectedMistakes.delete(val);
        } else {
          selectedMistakes.add(val);
        }
        if (selectedMistakes.size === 0) {
          selectedMistakes.add('None');
        }
      }
      updateMistakePillsUI();
    });
  });

  // Submit Trade Entry
  tradeForm.addEventListener('submit', (e) => {
    e.preventDefault();
    
    const tradeId = formTradeId.value;
    
    // Process strategy value
    let strategyVal = formStrategySelect.value;
    if (strategyVal === '__custom__') {
      const customName = formStrategyCustom.value.trim();
      if (customName) {
        stateManager.addStrategy(customName);
        strategyVal = customName;
      } else {
        strategyVal = 'Uncategorized';
      }
    }

    // Process emotion value
    let emotionVal = formEmotionSelect.value;
    if (emotionVal === '__custom__') {
      const customEmo = formEmotionCustom.value.trim();
      if (customEmo) {
        stateManager.addEmotion(customEmo);
        emotionVal = customEmo;
      } else {
        emotionVal = 'Neutral';
      }
    }

    const tradeData = {
      symbol: document.getElementById('form-symbol').value,
      side: document.getElementById('form-side').value,
      price: document.getElementById('form-price').value,
      stopLoss: document.getElementById('form-stoploss').value,
      pfMatrix: document.getElementById('form-pfmatrix').value,
      rsMatrix: document.getElementById('form-rsmatrix').value,
      xPercentage: document.getElementById('form-xpct').value,
      shares: document.getElementById('form-shares').value,
      strategy: strategyVal,
      emotion: emotionVal,
      date: new Date(document.getElementById('form-date').value).toISOString(),
      mistakes: Array.from(selectedMistakes),
      notes: document.getElementById('form-notes').value
    };

    marketFeed.addTicker(tradeData.symbol, tradeData.price);

    if (tradeId) {
      stateManager.editTrade(tradeId, tradeData);
      showToast("Trade entry updated successfully.", "success");
    } else {
      stateManager.addTrade(tradeData);
      showToast("New trade recorded successfully.", "success");
    }

    closeTradeModal();
    updateAllViews();
  });

  // Strategy addition
  strategyAddForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const name = strategyNewName.value.trim();
    if (name) {
      const added = stateManager.addStrategy(name);
      if (added) {
        showToast(`Strategy setup added: ${name}`, 'success');
        strategyNewName.value = '';
        updateAllViews();
      } else {
        showToast("Strategy name already exists or is invalid.", 'warning');
      }
    }
  });

  // Emotion addition
  emotionAddForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const name = emotionNewName.value.trim();
    if (name) {
      const added = stateManager.addEmotion(name);
      if (added) {
        showToast(`Emotion tag added: ${name}`, 'success');
        emotionNewName.value = '';
        updateAllViews();
      } else {
        showToast("Emotion tag already exists or is invalid.", 'warning');
      }
    }
  });

  // Filters triggers
  filterSearch.addEventListener('input', renderTradeLogView);
  filterSide.addEventListener('change', renderTradeLogView);
  filterStrategy.addEventListener('change', renderTradeLogView);
  filterEmotion.addEventListener('change', renderTradeLogView);

  // Export JSON
  btnExport.addEventListener('click', () => {
    const dataStr = stateManager.exportData();
    const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
    
    const exportFileDefaultName = 'stock_journal_export_' + new Date().toISOString().slice(0, 10) + '.json';
    
    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
    
    showToast("Journal database exported.");
  });

  // Import JSON
  btnImport.addEventListener('click', () => {
    fileImportInput.click();
  });

  fileImportInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(evt) {
      const contents = evt.target.result;
      const success = stateManager.importData(contents);
      if (success) {
        showToast("Journal data imported successfully!", "success");
        fileImportInput.value = '';
        updateAllViews();
      } else {
        showToast("Failed to parse JSON file. Check format.", "danger");
      }
    };
    reader.readAsText(file);
  });

  // Reset Mock Data
  btnResetMock.addEventListener('click', () => {
    if (confirm("This will reset all your trade log entries, strategies, and emotions to the default mock data. Continue?")) {
      stateManager.resetToMock();
      currentPrices = marketFeed.getCurrentPrices();
      showToast("Database restored to defaults.", "success");
      updateAllViews();
    }
  });

  // Initial render
  renderWatchlist();
  updateAllViews();
  
  stateManager.onLoad(() => {
    updateAllViews();
  });
  
  // Start simulation background tick listener
  startMarketTickerSubscription();
});
