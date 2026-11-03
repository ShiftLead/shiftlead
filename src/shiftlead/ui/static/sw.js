// The push service worker (design §4.10 *Told on the home-screen app too*, *The service worker*; TD-1305).
// Registered by the Settings page's **Push** card as `/sw.js?k=<public key>`, the home's VAPID public key in
// base64url. It draws every push it is handed, opens the row's page on a tap, and subscribes again when the
// browser replaces a subscription. No fetch handler and no cache: the app is never served from here.
"use strict";

const KEY = new URL(self.location.href).searchParams.get("k") || "";
const FALLBACK = { body: "something needs you", path: "/inbox", tag: "more" };

// A payload absent, not JSON, or missing a field is drawn as *something needs you* — a push is never dropped.
function payloadOf(data) {
  let got = null;
  try { got = data ? data.json() : null; } catch (e) { got = null; }
  const ok = got && typeof got === "object" && ["body", "path", "tag"].every((k) => typeof got[k] === "string" && got[k]);
  return ok ? { body: got.body, path: /^\/(?![\/\\])/.test(got.path) ? got.path : "/inbox", tag: got.tag } : FALLBACK;
}

self.addEventListener("push", (event) => {
  const p = payloadOf(event.data);
  event.waitUntil(self.registration.showNotification("shiftlead", {
    body: p.body, tag: p.tag, icon: "/static/icons/app-192.png", data: { path: p.path },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const path = (event.notification.data && event.notification.data.path) || "/inbox";
  const url = new URL(path, self.location.origin).href;
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) {
      if (new URL(w.url).origin !== self.location.origin) continue;
      await w.focus();
      if ("navigate" in w) { try { await w.navigate(url); } catch (e) { /* uncontrolled: focus is all */ } }
      return;
    }
    await self.clients.openWindow(url);
  })());
});

function b64url(buf) {
  const s = String.fromCharCode(...new Uint8Array(buf));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function fromB64url(s) {
  const raw = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}
// A device's id: the first 16 hex digits of the SHA-256 of its endpoint, as the home works it out.
async function deviceId(endpoint) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(endpoint));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 16);
}

// The device's label from the browser's user agent, as the page makes it: *iPhone · Safari*, *Linux · Firefox*.
function labelOf(ua) {
  const os = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android"
    : /Mac OS X|Macintosh/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : /CrOS/.test(ua) ? "ChromeOS" : /Linux/.test(ua) ? "Linux" : "a device";
  const br = /Edg\//.test(ua) ? "Edge" : /Firefox\/|FxiOS/.test(ua) ? "Firefox" : /Chrome\/|CriOS/.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "";
  return br ? `${os} · ${br}` : os;
}

// The browser replaced (or dropped) the subscription: subscribe again with the key and tell the home, naming the
// old device when the browser still says which it was, so its label and *since* are kept.
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil((async () => {
    if (!KEY) return;
    const sub = event.newSubscription || await self.registration.pushManager.subscribe({
      userVisibleOnly: true, applicationServerKey: fromB64url(KEY),
    });
    const j = sub.toJSON();
    const body = { endpoint: j.endpoint, keys: j.keys, key: KEY, label: labelOf(self.navigator.userAgent) };
    if (event.oldSubscription && event.oldSubscription.endpoint) body.replaces = await deviceId(event.oldSubscription.endpoint);
    await fetch("/api/settings/push_subscribe", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), credentials: "same-origin",
    });
  })());
});

// for tests and the page: what the worker would draw and whose id an endpoint is
self.__ao = { payloadOf, deviceId, labelOf, b64url, fromB64url };
