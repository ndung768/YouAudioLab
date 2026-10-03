function csrfToken() {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export function identityUserId() {
  return document.body.dataset.userId || "";
}

export async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  const token = csrfToken();
  if (token) headers.set("X-CSRFToken", token);
  const userId = identityUserId();
  if (userId) headers.set("X-User-Id", userId);
  const response = await fetch(path, { ...options, headers });
  return response;
}

export async function apiJson(path, options = {}) {
  const response = await apiFetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = body?.error?.message || response.statusText;
    throw new Error(message);
  }
  return body;
}
