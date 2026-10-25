// Static page for the VPC Provisioning API: vanilla JS, no framework, no build step.
// Login uses the Cognito hosted login with the authorization code flow + PKCE, so
// the page never sees the password and holds no secret.
"use strict";

(function () {
  const config = window.APP_CONFIG;

  // sessionStorage (not localStorage): the token disappears with the tab.
  const TOKEN_KEY = "access_token";
  const VERIFIER_KEY = "pkce_code_verifier";
  const STATE_KEY = "oauth_state";

  const element = (id) => document.getElementById(id);

  function base64UrlEncode(bytes) {
    let binary = "";
    for (const byte of bytes) {
      binary += String.fromCharCode(byte);
    }
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function randomBase64Url(byteLength) {
    const bytes = new Uint8Array(byteLength);
    crypto.getRandomValues(bytes);
    return base64UrlEncode(bytes);
  }

  async function sha256Base64Url(text) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return base64UrlEncode(new Uint8Array(digest));
  }

  // Always textContent, never innerHTML: API responses are untrusted data (XSS).
  function showMessage(text) {
    element("output").textContent = text;
  }

  function showResponse(status, body) {
    const rendered = typeof body === "string" ? body : JSON.stringify(body, null, 2);
    let text = `HTTP ${status}\n${rendered}`;
    if (status === 401) {
      text = `Session expired or missing, log in again\n\n${text}`;
    }
    showMessage(text);
  }

  function getToken() {
    return sessionStorage.getItem(TOKEN_KEY);
  }

  function updateSessionStatus() {
    element("session-status").textContent = getToken() ? "Logged in." : "Not logged in.";
  }

  async function login() {
    const verifier = randomBase64Url(32);
    const state = randomBase64Url(16);
    sessionStorage.setItem(VERIFIER_KEY, verifier);
    sessionStorage.setItem(STATE_KEY, state);
    const params = new URLSearchParams({
      response_type: "code",
      client_id: config.clientId,
      redirect_uri: config.redirectUri,
      scope: "openid",
      code_challenge_method: "S256",
      code_challenge: await sha256Base64Url(verifier),
      state: state,
    });
    window.location.assign(`https://${config.cognitoDomain}/oauth2/authorize?${params}`);
  }

  async function handleCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      if (params.get("error")) {
        history.replaceState(null, "", window.location.pathname);
        showMessage(`Login failed: ${params.get("error")}`);
      }
      return;
    }

    const expectedState = sessionStorage.getItem(STATE_KEY);
    const verifier = sessionStorage.getItem(VERIFIER_KEY);
    sessionStorage.removeItem(STATE_KEY);
    sessionStorage.removeItem(VERIFIER_KEY);
    // Remove code and state from the address bar and the browser history.
    history.replaceState(null, "", window.location.pathname);

    // CSRF protection: never exchange a code that this tab did not ask for.
    if (!expectedState || state !== expectedState || !verifier) {
      showMessage("Login failed: invalid state. Log in again.");
      return;
    }

    try {
      const response = await fetch(`https://${config.cognitoDomain}/oauth2/token`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          grant_type: "authorization_code",
          client_id: config.clientId,
          code: code,
          redirect_uri: config.redirectUri,
          code_verifier: verifier,
        }),
      });
      if (!response.ok) {
        showMessage(`Login failed: the token endpoint returned HTTP ${response.status}.`);
        return;
      }
      const tokens = await response.json();
      // The access token (not the ID token) is the one meant for API calls.
      sessionStorage.setItem(TOKEN_KEY, tokens.access_token);
      showMessage("Logged in.");
    } catch (error) {
      showMessage(`Login failed: ${error}`);
    }
  }

  async function callApi(method, path, body) {
    const headers = {};
    const token = getToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    const options = { method: method, headers: headers };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    try {
      const response = await fetch(`${config.apiUrl}${path}`, options);
      const text = await response.text();
      let parsed = text;
      try {
        parsed = text ? JSON.parse(text) : null;
      } catch (error) {
        // Not JSON: show the raw text.
      }
      showResponse(response.status, parsed);
    } catch (error) {
      showMessage(`Request failed: ${error}`);
    }
  }

  function createVpc(event) {
    event.preventDefault();
    const body = {
      name: element("name").value,
      cidr_block: element("cidr_block").value.trim(),
      subnet_count: Number(element("subnet_count").value),
    };
    const subnetPrefix = element("subnet_prefix").value.trim();
    if (subnetPrefix !== "") {
      body.subnet_prefix = Number(subnetPrefix);
    }
    callApi("POST", "/v1/vpcs", body);
  }

  function listVpcs() {
    callApi("GET", "/v1/vpcs");
  }

  function deleteVpc() {
    const id = element("delete-id").value.trim();
    if (!id) {
      showMessage("Enter the id of the VPC request to delete.");
      return;
    }
    callApi("DELETE", `/v1/vpcs/${encodeURIComponent(id)}`);
  }

  async function copyToken() {
    const token = getToken();
    if (!token) {
      showMessage("No access token: log in first.");
      return;
    }
    try {
      await navigator.clipboard.writeText(token);
      showMessage("Access token copied. Use it as: Authorization: Bearer <token>");
    } catch (error) {
      showMessage(`Could not copy the token: ${error}`);
    }
  }

  function logout() {
    sessionStorage.clear();
    const params = new URLSearchParams({
      client_id: config.clientId,
      logout_uri: config.redirectUri,
    });
    window.location.assign(`https://${config.cognitoDomain}/logout?${params}`);
  }

  async function init() {
    element("login").addEventListener("click", login);
    element("logout").addEventListener("click", logout);
    element("copy-token").addEventListener("click", copyToken);
    element("create-form").addEventListener("submit", createVpc);
    element("list").addEventListener("click", listVpcs);
    element("delete").addEventListener("click", deleteVpc);
    await handleCallback();
    updateSessionStatus();
  }

  init();
})();
