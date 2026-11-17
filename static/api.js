// Single entry point for every backend call.
//
// Every /api route requires a bearer token, so requests must wait for sign-in
// to finish and carry the token; a 401 means the session is gone and the user
// is signed out instead of being left with a silently empty dashboard.

import { getAuthToken, handleUnauthorized, authSuspended } from './auth.js?v=2.11';

export const getBaseUrl = () => window.FASTAPI_BACKEND_URL || window.API_BASE_URL || '';

export async function apiFetch(path, options = {}) {
  // After a 401 the session is parked on the sign-in gate: stop polling a
  // server that is rejecting the token until a fresh sign-in lands.
  if (authSuspended()) {
    throw new Error('Signed out after a 401 response.');
  }

  const token = await getAuthToken();
  const headers = new Headers(options.headers || {});

  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(`${getBaseUrl()}${path}`, { ...options, headers });

  if (response.status === 401) {
    await handleUnauthorized();
    throw new Error('Session expired. Please sign in again.');
  }

  return response;
}
