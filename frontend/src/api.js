export function getApiBase() {
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE;
  }
  const protocol = window.location.protocol;
  const hostname = window.location.hostname;
  return `${protocol}//${hostname}:9002`;
}

export async function apiGet(path) {
  const response = await fetch(`${getApiBase()}${path}`);
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

export async function apiPost(path, body) {
  const response = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
