// Clerk session handling for the static frontend.
//
// The publishable key is public by design: it only identifies the Clerk
// application. Sign-in happens inside Clerk's widget, and the resulting
// short-lived JWT is attached to every API call by api.js.

const publishableKey = window.CLERK_PUBLISHABLE_KEY || '';
const devMode = !publishableKey;

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

function loadClerkScript(frontendApi) {
  if (clerkScriptPromise) return clerkScriptPromise;

  clerkScriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.async = true;
    script.crossOrigin = 'anonymous';
    script.dataset.clerkPublishableKey = publishableKey;
    script.src = `https://${frontendApi}/npm/@clerk/clerk-js@5/dist/clerk.browser.js`;
    script.onload = resolve;
    script.onerror = () => reject(new Error('Could not load Clerk'));
    document.head.appendChild(script);
  });

  return clerkScriptPromise;
}

function revealApp() {
  document.body.classList.remove('auth-locked');
  gateElement()?.classList.add('hidden');
}

async function initAuth() {
  if (devMode) {
    revealApp();
    setNote('Dev mode: authentication is disabled for this deployment.');
    return;
  }

  document.body.classList.add('auth-locked');
  gateElement()?.classList.remove('hidden');

  const frontendApi = frontendApiFromKey(publishableKey);
  if (!frontendApi) {
    setNote('CLERK_PUBLISHABLE_KEY looks malformed.');
    throw new Error('Invalid Clerk publishable key');
  }

  await loadClerkScript(frontendApi);
  await window.Clerk.load();

  if (window.Clerk.session) {
    revealApp();
    return;
  }

  const mountPoint = document.getElementById('clerk-sign-in');
  if (mountPoint) {
    window.Clerk.mountSignIn(mountPoint, {
      appearance: { variables: { colorPrimary: '#8b5cf6', borderRadius: '10px' } },
    });
  }

  // Reload once a session appears so the app boots with a token in hand
  // instead of mixing pre-login localStorage with server data.
  await new Promise((resolve) => {
    window.Clerk.addListener(({ session }) => {
      if (session) {
        resolve();
        location.reload();
      }
    });
  });
}

export const authReady = initAuth().catch((error) => {
  console.error('Authentication could not start:', error);
  setNote('Sign-in is unavailable right now. Refresh to try again.');
});

export function authMode() {
  return devMode ? 'dev' : 'clerk';
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
  await signOut();
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
