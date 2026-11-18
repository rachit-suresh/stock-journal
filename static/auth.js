// Supabase session handling for the static frontend.
//
// Sign-in is email + password. supabase-js keeps the session in localStorage
// and refreshes the short-lived access token; api.js attaches that token to
// every request and the backend verifies it against the project's JWKS
// (app/core/security.py).
//
// The project URL and anon key are public by design — the anon key only
// identifies the project, and RLS keeps it away from the tables. They are read
// from GET /auth/config so every deployment value stays in the backend's env,
// and this file needs no edit between environments.

const SUPABASE_JS = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

// Verified tokens expire in an hour; refresh before the last half minute.
const REFRESH_WINDOW_MS = 30_000;
const MIN_PASSWORD_LENGTH = 6;

let supabase = null;
let devMode = false;
let formMode = 'signin'; // 'signin' | 'signup'
let submitting = false;

// Set when the API answers 401: the app returns to the gate and apiFetch stops
// calling a server that is rejecting the token.
let sessionRejected = false;
let currentSession = null;

const backendBaseUrl = () =>
  window.FASTAPI_BACKEND_URL || window.API_BASE_URL || '';

function byId(id) {
  return document.getElementById(id);
}

function gateElement() {
  return byId('auth-gate');
}

function setNote(text) {
  const note = byId('auth-note');
  if (note) note.textContent = text;
}

function revealApp() {
  document.body.classList.remove('auth-locked');
  gateElement()?.classList.add('hidden');
}

function lockToGate(message) {
  document.body.classList.add('auth-locked');
  gateElement()?.classList.remove('hidden');
  if (message !== undefined) setNote(message);
}

/** Swap the form between "sign in" and "create account". */
function renderForm() {
  const submit = byId('auth-submit');
  const toggle = byId('auth-toggle');
  const password = byId('auth-password');
  if (!submit || !toggle) return;

  const signup = formMode === 'signup';
  submit.textContent = signup ? 'Create account' : 'Sign in';
  submit.disabled = submitting;
  toggle.textContent = signup
    ? 'Already have an account? Sign in'
    : 'New here? Create an account';
  if (password) {
    password.setAttribute('autocomplete', signup ? 'new-password' : 'current-password');
  }
}

function showForm() {
  const form = byId('auth-form');
  if (form) form.hidden = false;
  renderForm();
  byId('auth-email')?.focus();
}

/** Turn Supabase's raw error messages into something a user can act on. */
function friendlyError(error) {
  const message = error?.message || String(error);
  const lower = message.toLowerCase();
  if (lower.includes('invalid login credentials')) {
    return 'Wrong email or password. If you have no account yet, create one below.';
  }
  if (lower.includes('email not confirmed')) {
    return 'This account still needs its email confirmed. Check your inbox, then sign in.';
  }
  if (lower.includes('already registered')) {
    return 'That email already has an account. Sign in instead.';
  }
  if (lower.includes('password should be at least')) {
    return `Passwords need at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (lower.includes('failed to fetch') || lower.includes('load failed')) {
    return 'Could not reach Supabase. Check the network connection and try again.';
  }
  return message;
}

async function onSubmit(event) {
  event.preventDefault();
  if (!supabase || submitting) return;

  const email = byId('auth-email')?.value.trim() || '';
  const password = byId('auth-password')?.value || '';
  if (!email || !password) {
    setNote('Enter your email and password.');
    return;
  }
  if (formMode === 'signup' && password.length < MIN_PASSWORD_LENGTH) {
    setNote(`Passwords need at least ${MIN_PASSWORD_LENGTH} characters.`);
    return;
  }

  submitting = true;
  renderForm();
  setNote(formMode === 'signup' ? 'Creating your account…' : 'Signing in…');

  try {
    if (formMode === 'signup') {
      const { data, error } = await supabase.auth.signUp({ email, password });
      if (error) throw error;
      if (!data.session) {
        // "Confirm email" is still switched on for this Supabase project.
        setNote('Account created. Confirm the email Supabase sent, then sign in.');
        formMode = 'signin';
        return;
      }
    } else {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
    }
    // The auth listener reveals the app; don't leave the password behind.
    const passwordField = byId('auth-password');
    if (passwordField) passwordField.value = '';
  } catch (error) {
    setNote(friendlyError(error));
  } finally {
    submitting = false;
    // A successful sign-in tears the gate down, so only touch it if it is
    // still on screen.
    if (document.body.classList.contains('auth-locked')) renderForm();
  }
}

function toggleFormMode() {
  formMode = formMode === 'signup' ? 'signin' : 'signup';
  setNote('');
  renderForm();
  byId('auth-email')?.focus();
}

async function readConfig() {
  // A deployment may pin both values in index.html instead of asking the API.
  if (window.SUPABASE_URL && window.SUPABASE_ANON_KEY) {
    return { url: window.SUPABASE_URL, anonKey: window.SUPABASE_ANON_KEY };
  }

  const response = await fetch(`${backendBaseUrl()}/auth/config`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`GET /auth/config returned ${response.status}`);
  }
  const config = await response.json();
  if (config.provider !== 'supabase') return null; // server side AUTH_DISABLED
  if (!config.url || !config.anonKey) {
    throw new Error('the server has no SUPABASE_URL / SUPABASE_ANON_KEY configured');
  }
  return { url: config.url, anonKey: config.anonKey };
}

async function initAuth() {
  const config = await readConfig();
  if (!config) {
    devMode = true;
    revealApp();
    setNote('Dev mode: authentication is disabled for this deployment.');
    return;
  }

  lockToGate('Connecting…');

  const { createClient } = await import(SUPABASE_JS);
  supabase = createClient(config.url, config.anonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      // No email-link/OAuth return trip: the URL never carries a session.
      detectSessionInUrl: false,
    },
  });

  let settle;
  const ready = new Promise((resolve) => { settle = resolve; });

  // One listener for the page lifetime: it reveals the app on the first
  // session and again after a rejected session sent the user back to the gate.
  supabase.auth.onAuthStateChange((event, session) => {
    currentSession = session || null;
    if (!session) return;

    const comingBack = sessionRejected;
    sessionRejected = false;
    setNote('');
    if (comingBack) {
      // The journal was already rendered from the offline fallback, so a
      // single reload is the cheapest way to boot again with server data.
      location.reload();
      return;
    }
    revealApp();
    settle();
  });

  const { data } = await supabase.auth.getSession();
  currentSession = data.session || null;
  if (currentSession) {
    revealApp();
    return;
  }

  showForm();
  await ready;
}

export const authReady = initAuth().catch((error) => {
  console.error('Authentication could not start:', error);
  lockToGate(`Sign-in is unavailable: ${error?.message || error}`);
});

export function authMode() {
  return devMode ? 'dev' : 'supabase';
}

/** True once the server rejected a token: stop sending requests until sign-in. */
export function authSuspended() {
  return sessionRejected;
}

export async function getAuthToken() {
  await authReady;
  if (devMode || !supabase) return null;

  let session = currentSession;
  if (!session) {
    const { data } = await supabase.auth.getSession();
    session = data.session;
  }
  if (!session) return null;

  const expiresAt = (session.expires_at || 0) * 1000;
  if (expiresAt && expiresAt - Date.now() < REFRESH_WINDOW_MS) {
    const { data, error } = await supabase.auth.refreshSession();
    if (error) {
      console.warn('Could not refresh the Supabase session:', error.message);
      return session.access_token;
    }
    currentSession = data.session || null;
    return data.session?.access_token || null;
  }

  return session.access_token;
}

export function clearLocalJournalKeys() {
  try {
    Object.keys(localStorage)
      .filter((key) => key.startsWith('stock_journal_'))
      .forEach((key) => localStorage.removeItem(key));
  } catch (error) {
    console.warn('Could not clear local cache:', error);
  }
}

export async function handleUnauthorized() {
  if (devMode) {
    console.warn('API rejected the request although auth is disabled (dev mode).');
    return;
  }
  if (sessionRejected) return;
  sessionRejected = true;

  console.warn('The API rejected the bearer token; returning to the sign-in gate.');
  // Sign out without reloading: the reload used to bounce the user between the
  // gate and the dashboard whenever the backend rejected every token.
  try {
    await supabase?.auth.signOut({ scope: 'local' });
  } catch (error) {
    console.warn('Supabase sign-out failed:', error);
  }
  currentSession = null;
  clearLocalJournalKeys();
  lockToGate(
    'Your session is no longer valid. Sign in again — if this repeats, the ' +
    'backend\'s SUPABASE_URL must match this sign-in page\'s project.'
  );
}

export async function signOut() {
  try {
    await supabase?.auth.signOut();
  } catch (error) {
    console.warn('Supabase sign-out failed:', error);
  }
  currentSession = null;
  clearLocalJournalKeys();
  location.reload();
}

export function currentUserEmail() {
  return currentSession?.user?.email || '';
}

function wireGate() {
  byId('auth-form')?.addEventListener('submit', onSubmit);
  byId('auth-toggle')?.addEventListener('click', toggleFormMode);
}

wireGate();

authReady.then(() => {
  const emailSlot = byId('account-email');
  if (emailSlot) emailSlot.textContent = devMode ? 'Dev mode' : currentUserEmail();
});

byId('btn-signout')?.addEventListener('click', () => signOut());
