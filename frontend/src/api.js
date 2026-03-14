export function getApiBase() {
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE;
  }
  const protocol = window.location.protocol;
  const hostname = window.location.hostname;
  return `${protocol}//${hostname}:9002`;
}

function requestHeaders(extraHeaders = {}) {
  return { ...extraHeaders };
}

function adminHeaders() {
  const token = import.meta.env.VITE_ADMIN_TOKEN;
  if (!token) {
    return {};
  }
  return { "X-Synthia-Admin-Token": token };
}

export async function apiGet(path, extraHeaders = {}) {
  const response = await fetch(`${getApiBase()}${path}`, {
    headers: requestHeaders(extraHeaders),
  });
  const payload = await response.json();
  if (!response.ok) {
    const detail = payload.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message || detail?.error_code || payload.error || `request failed (${response.status})`;
    throw new Error(message);
  }
  return payload;
}

export async function apiPost(path, body, extraHeaders = {}) {
  const response = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    headers: requestHeaders({ "Content-Type": "application/json", ...extraHeaders }),
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    const detail = payload.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message || detail?.error_code || payload.error || `request failed (${response.status})`;
    throw new Error(message);
  }
  return payload;
}

export async function apiAdminGet(path) {
  return apiGet(path, adminHeaders());
}

export async function apiAdminPost(path, body) {
  return apiPost(path, body, adminHeaders());
}
