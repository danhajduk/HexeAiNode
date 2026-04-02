function getProxiedNodeApiBase() {
  const pathname = String(window.location.pathname || "").trim();
  const match = pathname.match(/^\/nodes\/([^/]+)\/ui(?:\/.*)?$/i);
  if (!match) {
    return "";
  }
  const nodeId = decodeURIComponent(match[1]);
  return `${window.location.origin}/api/nodes/${nodeId}`;
}

export function getApiBase() {
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE;
  }
  const proxiedNodeApiBase = getProxiedNodeApiBase();
  if (proxiedNodeApiBase) {
    return proxiedNodeApiBase;
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

function formatBlockingReasons(blockingReasons) {
  if (!Array.isArray(blockingReasons) || !blockingReasons.length) {
    return "";
  }
  return blockingReasons.filter(Boolean).join(", ");
}

function buildApiError(response, payload) {
  const detail = payload?.detail;
  const baseMessage =
    typeof detail === "string"
      ? detail
      : detail?.message || detail?.error_code || payload?.error || `request failed (${response.status})`;
  const blockingReasonsMessage = formatBlockingReasons(detail?.blocking_reasons);
  const message = blockingReasonsMessage ? `${baseMessage}: ${blockingReasonsMessage}` : baseMessage;
  const error = new Error(message);
  error.detail = detail;
  error.status = response.status;
  return error;
}

export async function apiGet(path, extraHeaders = {}) {
  const response = await fetch(`${getApiBase()}${path}`, {
    headers: requestHeaders(extraHeaders),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw buildApiError(response, payload);
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
    throw buildApiError(response, payload);
  }
  return payload;
}

export async function apiAdminGet(path) {
  return apiGet(path, adminHeaders());
}

export async function apiAdminPost(path, body) {
  return apiPost(path, body, adminHeaders());
}
