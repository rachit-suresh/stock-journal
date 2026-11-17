// Single entry point for every backend call.
//
// Every /api route requires a bearer token, so requests must wait for sign-in
// to finish and carry the token; a 401 means the session is gone and the user
// is signed out instead of being left with a silently empty dashboard.

import { getAuthToken, handleUnauthorized } from './auth.js';

export const getBaseUrl = () => window.FASTAPI_BACKEND_URL || window.API_BASE_URL || '';

export async function apiFetch(path, options = {}) {
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
