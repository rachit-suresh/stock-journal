// Clerk session handling for the static frontend.
//
// The publishable key is public by design: it only identifies the Clerk
// application. Sign-in happens inside Clerk's widget, and the resulting
// short-lived JWT is attached to every API call by api.js.

const publishableKey = window.CLERK_PUBLISHABLE_KEY || '';
const devMode = !publishableKey;

// Pin the clerk-js major to the one current instances accept. The CDN's
// `@latest` alias still resolves to the legacy 4.x bundle, and an older major
// mounts a widget that then refuses to sign in ("outdated version of Clerk").
const CLERK_JS_MAJOR = '@6';

// Since v5 the widgets ship as a separate bundle. Loading clerk-js alone leaves
// the mount node empty and every mount*() call throws
// "Clerk was not loaded with Ui components".
const CLERK_UI_MAJOR = '@1';

let clerkScriptPromise = null;

function gateElement() {
  return document.getElementById('auth-gate');
}

function setNote(text) {
  const note = document.getElementById('auth-note');
  if (note) note.textContent = text;
}

/** Clerk publishable keys embed the Frontend API host in base64. */
function frontendApiFromKey(key) {
  try {
    const encoded = key.split('_').slice(2).join('_');
    const padded = encoded.padEnd(Math.ceil(encoded.length / 4) * 4, '=');
    return atob(padded).replace(/\$$/, '');
  } catch (e) {
    console.error('Could not parse CLERK_PUBLISHABLE_KEY', e);
    return '';
  }
}

function injectScript(src, attributes = {}) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.async = true;
    script.crossOrigin = 'anonymous';
    script.src = src;
    for (const [name, value] of Object.entries(attributes)) {
      script.setAttribute(name, value);
    }
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Could not load ${src}`));
    document.head.appendChild(script);
  });
}

/**
 * Loads both Clerk bundles from the instance's CDN, in the documented order:
 * the UI bundle first (it defines the component constructor), then clerk-js
 * (which defines window.Clerk). Both are served by the Frontend API host.
 */
function loadClerkScript(frontendApi) {
  if (clerkScriptPromise) return clerkScriptPromise;

  clerkScriptPromise = (async () => {
    if (!window.__internal_ClerkUICtor) {
      const uiSrc = `https://${frontendApi}/npm/@clerk/ui${CLERK_UI_MAJOR}/dist/ui.browser.js`;
      await injectScript(uiSrc);
      if (!window.__internal_ClerkUICtor) {
        throw new Error(`${uiSrc} did not register window.__internal_ClerkUICtor`);
      }
    }

    const jsSrc = `https://${frontendApi}/npm/@clerk/clerk-js${CLERK_JS_MAJOR}/dist/clerk.browser.js`;
    await injectScript(jsSrc, { 'data-clerk-publishable-key': publishableKey });
    if (!window.Clerk) {
      throw new Error(`${jsSrc} did not expose window.Clerk`);
    }
  })();

  return clerkScriptPromise;
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

let signInMounted = false;

function mountSignInOnce() {
  const mountPoint = document.getElementById('clerk-sign-in');
  if (!mountPoint || signInMounted) return;
  window.Clerk.mountSignIn(mountPoint, {
    appearance: { variables: { colorPrimary: '#8b5cf6', borderRadius: '10px' } },
  });
  signInMounted = true;
}

// Set when the API answers 401: the app returns to the gate and apiFetch stops
// calling a server that is rejecting the token.
let sessionRejected = false;

async function initAuth() {
  if (devMode) {
    revealApp();
    setNote('Dev mode: authentication is disabled for this deployment.');
    return;
  }

  lockToGate('');

  const frontendApi = frontendApiFromKey(publishableKey);
  if (!frontendApi) {
    setNote('CLERK_PUBLISHABLE_KEY looks malformed.');
    throw new Error('Invalid Clerk publishable key');
  }

  await loadClerkScript(frontendApi);
  // v6 requires the component constructor to be handed over explicitly,
  // otherwise the widget host stays empty.
  await window.Clerk.load({ ui: { ClerkUI: window.__internal_ClerkUICtor } });

  // One listener for the page lifetime: it reveals the app on the first
  // session and again after a rejected session sent the user back to the gate.
  let settle;
  const ready = new Promise((resolve) => { settle = resolve; });

  window.Clerk.addListener(({ session }) => {
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

  if (window.Clerk.session) {
    revealApp();
    settle();
  } else {
    mountSignInOnce();
  }

  await ready;
}

export const authReady = initAuth().catch((error) => {
  console.error('Authentication could not start:', error);
  // Surface the real cause instead of a generic note: the usual suspects are a
  // blocked Clerk script, a rejected origin, or a mismatched instance.
  lockToGate(`Sign-in is unavailable: ${error?.message || error}`);
});

export function authMode() {
  return devMode ? 'dev' : 'clerk';
}

/** True once the server rejected a token: stop sending requests until sign-in. */
export function authSuspended() {
  return sessionRejected;
}

export async function getAuthToken() {
  await authReady;
  if (devMode || !window.Clerk?.session) return null;
  try {
    return await window.Clerk.session.getToken();
  } catch (error) {
    console.warn('Could not read a Clerk session token:', error);
    return null;
  }
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

  const host = frontendApiFromKey(publishableKey);
  console.warn('The API rejected the bearer token; returning to the sign-in gate.');
  // Sign out without reloading: the reload used to bounce the user between the
  // gate and the dashboard whenever the backend rejected every token.
  try {
    await window.Clerk?.signOut();
  } catch (error) {
    console.warn('Clerk sign-out failed:', error);
  }
  clearLocalJournalKeys();
  lockToGate(
    `The server rejected your session (401). Sign in again — if this repeats, ` +
    `CLERK_ISSUER on the backend must be https://${host}.`
  );
}

export async function signOut() {
  try {
    await window.Clerk?.signOut();
  } catch (error) {
    console.warn('Clerk sign-out failed:', error);
  }
  clearLocalJournalKeys();
  location.reload();
}

export function currentUserEmail() {
  return window.Clerk?.user?.primaryEmailAddress?.emailAddress || '';
}

document.addEventListener('DOMContentLoaded', () => {
  const emailSlot = document.getElementById('account-email');
  const signOutButton = document.getElementById('btn-signout');

  if (signOutButton) {
    signOutButton.addEventListener('click', () => signOut());
  }

  authReady.then(() => {
    if (!emailSlot) return;
    emailSlot.textContent = devMode ? 'Dev mode' : currentUserEmail();
  });
});
