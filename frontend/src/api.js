/** Same-origin API helpers (session cookie auth). */

export async function apiJson(path, options = {}) {
  const res = await fetch(path, { credentials: 'include', ...options });
  if (!res.ok) {
    const err = new Error(res.statusText || `HTTP ${res.status}`);
    err.status = res.status;
    try {
      err.body = await res.json();
    } catch {
      err.body = null;
    }
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

async function postForm(path, fields) {
  const body = new URLSearchParams(fields);
  const res = await fetch(path, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}`);
    err.status = res.status;
    try {
      err.body = await res.json();
    } catch {
      err.body = null;
    }
    throw err;
  }
  return res.json();
}

/**
 * Submit the first-factor credentials. Returns `{ ok, username }` for users
 * without 2FA enrolled, or `{ ok, needs_2fa: true }` when the caller must
 * follow up with `verifyTotp(code)` before they're fully signed in.
 */
export async function login(username, password) {
  return postForm('/login', { username, password });
}

export async function logout() {
  return apiJson('/logout', { method: 'POST' });
}

export async function verifyTotp(code) {
  return postForm('/auth/totp/verify', { code });
}

export async function setupTotp() {
  return apiJson('/auth/totp/setup', { method: 'POST' });
}

export async function enableTotp(code) {
  return postForm('/auth/totp/enable', { code });
}

export async function disableTotp(code) {
  return postForm('/auth/totp/disable', { code });
}

// ---------- WebAuthn / passkeys ----------

export async function registerPasskeyBegin() {
  return apiJson('/auth/webauthn/register/begin', { method: 'POST' });
}

export async function registerPasskeyFinish(body) {
  return apiJson('/auth/webauthn/register/finish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function listPasskeys() {
  return apiJson('/auth/webauthn/credentials');
}

export async function deletePasskey(id) {
  return apiJson(`/auth/webauthn/credentials/${id}`, { method: 'DELETE' });
}

export async function loginPasskeyBegin() {
  return apiJson('/auth/webauthn/login/begin', { method: 'POST' });
}

export async function loginPasskeyFinish(body) {
  return apiJson('/auth/webauthn/login/finish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}
