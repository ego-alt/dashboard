/**
 * Passkey helpers.
 *
 * The server sends options with base64url-encoded ArrayBuffer fields; the
 * browser's WebAuthn API needs actual ArrayBuffers. And vice versa for the
 * credential response we send back. These helpers handle the conversion.
 */

function b64uToBytes(s) {
  let str = s.replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  const bin = atob(str);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

function bytesToB64u(buf) {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function decodeRegistrationOptions(opts) {
  return {
    ...opts,
    challenge: b64uToBytes(opts.challenge),
    user: { ...opts.user, id: b64uToBytes(opts.user.id) },
    excludeCredentials: (opts.excludeCredentials || []).map((c) => ({
      ...c,
      id: b64uToBytes(c.id),
    })),
  };
}

function decodeAuthenticationOptions(opts) {
  return {
    ...opts,
    challenge: b64uToBytes(opts.challenge),
    allowCredentials: (opts.allowCredentials || []).map((c) => ({
      ...c,
      id: b64uToBytes(c.id),
    })),
  };
}

function encodeRegistrationCredential(cred) {
  return {
    id: cred.id,
    rawId: bytesToB64u(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: bytesToB64u(cred.response.clientDataJSON),
      attestationObject: bytesToB64u(cred.response.attestationObject),
      ...(typeof cred.response.getTransports === 'function' && {
        transports: cred.response.getTransports() || [],
      }),
    },
    ...(cred.authenticatorAttachment && {
      authenticatorAttachment: cred.authenticatorAttachment,
    }),
  };
}

function encodeAuthenticationCredential(cred) {
  return {
    id: cred.id,
    rawId: bytesToB64u(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: bytesToB64u(cred.response.clientDataJSON),
      authenticatorData: bytesToB64u(cred.response.authenticatorData),
      signature: bytesToB64u(cred.response.signature),
      ...(cred.response.userHandle && {
        userHandle: bytesToB64u(cred.response.userHandle),
      }),
    },
    ...(cred.authenticatorAttachment && {
      authenticatorAttachment: cred.authenticatorAttachment,
    }),
  };
}

import {
  loginPasskeyBegin,
  loginPasskeyFinish,
  registerPasskeyBegin,
  registerPasskeyFinish,
} from './api';

/** Run a full passkey registration with the current logged-in session. */
export async function registerPasskey(name) {
  const { token, options } = await registerPasskeyBegin();
  const created = await navigator.credentials.create({
    publicKey: decodeRegistrationOptions(options),
  });
  return registerPasskeyFinish({
    token,
    name: name || 'Passkey',
    credential: encodeRegistrationCredential(created),
  });
}

/** Run a full passkey assertion to sign in. */
export async function signInWithPasskey() {
  const { token, options } = await loginPasskeyBegin();
  const assertion = await navigator.credentials.get({
    publicKey: decodeAuthenticationOptions(options),
  });
  return loginPasskeyFinish({
    token,
    credential: encodeAuthenticationCredential(assertion),
  });
}

export function passkeysSupported() {
  return (
    typeof window !== 'undefined' &&
    window.PublicKeyCredential !== undefined &&
    typeof navigator?.credentials?.create === 'function'
  );
}
