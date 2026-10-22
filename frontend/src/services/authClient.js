const UNAVAILABLE = "AQUA sign-in is temporarily unavailable. Please try again.";

export class AuthError extends Error {
  constructor(status, message = UNAVAILABLE) {
    super(message);
    this.name = "AuthError";
    this.status = status;
  }
}

function safeError(status) {
  if (status === 401) return new AuthError(status, "Your sign-in could not be verified. Please sign in again.");
  if (status === 403) return new AuthError(status, "Please start a new sign-in attempt and try again.");
  return new AuthError(status);
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new AuthError(503);
  }
  if (!response.ok) throw safeError(response.status);
  if (response.status === 204) return null;
  try {
    return await response.json();
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new AuthError(502);
  }
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function capabilitiesResponse(capabilities) {
  if (!capabilities || typeof capabilities !== "object" || Array.isArray(capabilities)
    || Object.keys(capabilities).length > 16
    || Object.entries(capabilities).some(([key, value]) => !/^[a-z][a-z0-9_]{0,47}$/.test(key)
      || ["__proto__", "prototype", "constructor"].includes(key) || typeof value !== "boolean")) {
    throw new AuthError(502);
  }
  return { ...capabilities };
}

export function sessionResponse(body) {
  const user = body?.user;
  if (!user || typeof user !== "object" || Array.isArray(user)
    || typeof user.id !== "string" || !UUID.test(user.id) || /^0{8}-0{4}-0{4}-0{4}-0{12}$/.test(user.id)
    || (user.sub !== undefined && (typeof user.sub !== "string" || !user.sub || user.sub.length > 255))
    || typeof user.email !== "string" || user.email.length > 254
    || typeof user.name !== "string" || user.name.length > 256
    || typeof user.picture !== "string" || user.picture.length > 2048
    || typeof body.csrf_token !== "string" || !body.csrf_token || body.csrf_token.length > 512
    || typeof body.can_query !== "boolean") {
    throw new AuthError(502);
  }
  const identity = { id: user.id.toLowerCase(), email: user.email, name: user.name, picture: user.picture };
  if (user.sub !== undefined) identity.sub = user.sub;
  const session = { user: identity, csrf_token: body.csrf_token, can_query: body.can_query };
  if (body.capabilities !== undefined) {
    session.capabilities = capabilitiesResponse(body.capabilities);
  }
  return session;
}

export async function fetchAuthConfig({ signal } = {}) {
  const body = await request("/api/auth/config", { signal });
  if (!body || !["client_id", "nonce", "csrf_token"].every((key) => typeof body[key] === "string" && body[key])) {
    throw new AuthError(502);
  }
  return { client_id: body.client_id, nonce: body.nonce, csrf_token: body.csrf_token,
    ...(body.capabilities === undefined ? {} : { capabilities: capabilitiesResponse(body.capabilities) }) };
}

export async function fetchSession({ signal } = {}) {
  try {
    return sessionResponse(await request("/api/auth/me", { signal }));
  } catch (error) {
    if (error instanceof AuthError && error.status === 401) return null;
    throw error;
  }
}

export async function signInWithGoogle({ credential, csrfToken, signal }) {
  if (typeof credential !== "string" || !credential || typeof csrfToken !== "string" || !csrfToken) {
    throw new AuthError(401, "Please start a new sign-in attempt and try again.");
  }
  return sessionResponse(await request("/api/auth/google", {
    method: "POST", signal,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ credential })
  }));
}

export async function signOut({ csrfToken, signal }) {
  if (typeof csrfToken !== "string" || !csrfToken) throw safeError(401);
  await request("/api/auth/logout", { method: "POST", signal, headers: { "X-CSRF-Token": csrfToken } });
}
