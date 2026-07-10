/**
 * Shared axios auth wiring (Phase 1 #1).
 *
 * MomentumX is a single-user internal tool protected by one static
 * API_ACCESS_TOKEN (see backend/.env + backend/auth.py). This module
 * attaches that token to every outgoing request via an axios request
 * interceptor, and clears it + notifies the app on a 401 response.
 *
 * Since `axios` is a singleton module, setting up the interceptor once
 * here (imported by App.js before any page renders) covers every page
 * file that does `import axios from "axios"` - no per-file changes needed.
 */
import axios from "axios";

const TOKEN_KEY = "momentumx_api_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

axios.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

axios.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      clearToken();
      window.dispatchEvent(new Event("momentumx-unauthorized"));
    }
    return Promise.reject(error);
  }
);

export default axios;
