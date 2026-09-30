export function isCoreProxiedUi(pathname) {
  return /^\/nodes\/proxy\/ui\/[^/]+(?:\/.*)?$/i.test(String(pathname || ""));
}

export function buildCoreProxyRedirect(config, locationObject = window.location) {
  const proxyUrl = String(config?.proxy_ui_url || "").trim();
  if (!proxyUrl) {
    return null;
  }
  const route = String(locationObject.hash || "").trim() || "#/dashboard";
  return `${proxyUrl.replace(/\/$/, "")}/${route}`;
}

export async function redirectDirectUiToCore(locationObject = window.location, fetchImpl = fetch) {
  if (isCoreProxiedUi(locationObject.pathname)) {
    return false;
  }
  try {
    const response = await fetchImpl("/ui-config.json", { cache: "no-store" });
    if (!response.ok) {
      return false;
    }
    const redirectUrl = buildCoreProxyRedirect(await response.json(), locationObject);
    if (!redirectUrl) {
      return false;
    }
    locationObject.replace(redirectUrl);
    return true;
  } catch (_error) {
    return false;
  }
}
