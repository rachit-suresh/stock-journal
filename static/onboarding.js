/**
 * Walkthrough behind the "Walkthrough & Help" button.
 *
 * The journal has no demo content, so this is where the flow is explained:
 * pick stocks from your own portfolio, record trades against an instrument
 * key, tag the psychology, then read the analytics. It never opens itself -
 * there is no first-run state to keep in sync, just a button.
 */

const STEPS = [
  {
    title: 'Everything here is yours',
    text: 'StockJournal is a personal trading journal. There are no sample trades and no demo watchlist: you add the stocks you actually follow, and every number you see comes from your own entries.',
    bullets: [
      'You are signed in with your own email and password.',
      'Prices, P&L and statistics are in rupees (₹).',
      'Nothing you record here is shown to another account.'
    ]
  },
  {
    title: 'Step 1 — Add your stocks',
    text: 'Stocks are identified by their Upstox instrument key: the exchange segment, then the ISIN. That key is what pulls a live price.',
    bullets: [
      'Example: NSE_EQ|INE002A01018 is SBIN on the NSE.',
      'Record a trade with the key and the position gets a live quote.',
      'Dashboard → Your Watchlist lets you watch a price without recording a trade.'
    ],
    action: { label: 'Open my watchlist', name: 'watchlist' }
  },
  {
    title: 'Step 2 — Record a trade',
    text: 'Every buy or sell you make goes into the Trade Log, with the price you actually got filled at.',
    bullets: [
      'Symbol is your short label: RELIANCE, TCS, SBIN.',
      'Execution price and stop loss are in ₹; shares is the quantity.',
      'The instrument key is optional — without it the trade is journaled but has no live quote.'
    ],
    action: { label: 'Record my first trade', name: 'record-trade' }
  },
  {
    title: 'Step 3 — Tag the psychology',
    text: 'A journal only helps if it records why you took the trade, not just what you did.',
    bullets: [
      'Strategy is the setup you traded (breakout, pullback, gap fill…).',
      'Emotion is your mindset at entry — FOMO and greed belong here too.',
      'Mistakes and notes are the lessons you want to read six months from now.'
    ]
  },
  {
    title: 'Step 4 — Review and learn',
    text: 'Once trades exist, the other views start telling you something.',
    bullets: [
      'Dashboard: net equity, realized and unrealized P&L, open positions.',
      'Trade Log: search and filter every entry; click a row for the full detail.',
      'Analytics: win rate and net profit per strategy and per emotion.',
      'Export Journal keeps a JSON backup; Import Journal restores one.'
    ]
  },
  {
    title: 'Reading the live feed badge',
    text: 'The badge in the header reports the feed honestly, so a closed market never looks like a live one.',
    bullets: [
      'LIVE FEED ACTIVE means ticks are arriving right now.',
      'NO LIVE TICKS — LAST 12m AGO means the data is frozen, not wrong.',
      'WAITING FOR LIVE TICKS means no instrument key has been streamed yet.',
      'NSE trades 09:15–15:30 IST on weekdays.'
    ]
  }
];

export function mountTour() {
  const modal = document.getElementById('modal-tour');
  const noop = { open: () => {}, close: () => {}, isOpen: () => false };
  if (!modal) return noop;

  const titleEl = document.getElementById('tour-step-title');
  const textEl = document.getElementById('tour-step-text');
  const listEl = document.getElementById('tour-list');
  const progressEl = document.getElementById('tour-progress');
  const actionEl = document.getElementById('tour-action');
  const prevEl = document.getElementById('tour-prev');
  const nextEl = document.getElementById('tour-next');
  const skipEl = document.getElementById('tour-skip');
  const closeEl = document.getElementById('tour-close');

  let index = 0;
  let lastFocus = null;

  function render() {
    const step = STEPS[index];

    titleEl.textContent = step.title;
    textEl.textContent = step.text;

    listEl.innerHTML = '';
    (step.bullets || []).forEach(bullet => {
      const li = document.createElement('li');
      li.textContent = bullet;
      listEl.appendChild(li);
    });
    listEl.hidden = !step.bullets || step.bullets.length === 0;

    if (step.action) {
      actionEl.hidden = false;
      actionEl.textContent = step.action.label;
      actionEl.dataset.action = step.action.name;
    } else {
      actionEl.hidden = true;
      actionEl.textContent = '';
      actionEl.dataset.action = '';
    }

    progressEl.innerHTML = '';
    STEPS.forEach((_, i) => {
      const dot = document.createElement('span');
      dot.className = i === index ? 'tour-dot active' : 'tour-dot';
      progressEl.appendChild(dot);
    });

    prevEl.disabled = index === 0;
    nextEl.textContent = index === STEPS.length - 1 ? 'Finish' : 'Next';
  }

  function open() {
    index = 0;
    lastFocus = document.activeElement;
    render();
    modal.classList.add('active');
    nextEl.focus();
  }

  function close() {
    if (!modal.classList.contains('active')) return;
    modal.classList.remove('active');
    if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();
  }

  function go(step) {
    if (step < 0 || step >= STEPS.length) return;
    index = step;
    render();
  }

  function finish() {
    close();
  }

  nextEl.addEventListener('click', () => {
    if (index >= STEPS.length - 1) finish();
    else go(index + 1);
  });
  prevEl.addEventListener('click', () => go(index - 1));
  skipEl.addEventListener('click', finish);
  closeEl.addEventListener('click', finish);

  actionEl.addEventListener('click', () => {
    const action = actionEl.dataset.action;
    if (!action) return;
    document.dispatchEvent(new CustomEvent('sj:tour-action', { detail: { action } }));
  });

  // Close on a backdrop click, without swallowing clicks inside the card.
  modal.addEventListener('click', (event) => {
    if (event.target === modal) finish();
  });

  document.addEventListener('keydown', (event) => {
    if (!modal.classList.contains('active')) return;
    if (event.key === 'Escape') finish();
    else if (event.key === 'ArrowRight') nextEl.click();
    else if (event.key === 'ArrowLeft' && index > 0) go(index - 1);
  });

  return {
    open,
    close,
    isOpen: () => modal.classList.contains('active')
  };
}
