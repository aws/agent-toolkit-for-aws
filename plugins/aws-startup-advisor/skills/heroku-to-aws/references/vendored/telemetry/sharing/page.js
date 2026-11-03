"use strict";
const token = location.hash.slice(1);
history.replaceState(null, "", "/");
const el = id => document.getElementById(id);
async function api(path, body) {
  const options = {headers: {"X-Sharing-Token": token}, cache: "no-store"};
  if (body) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (!response.ok) throw new Error("Page unavailable");
  return response.json();
}
async function choose(choice) {
  el("result").textContent = choice === "AWS_ACCOUNT" ? "Checking your selected AWS account…" : "Saving your choice…";
  el("sign-in-help").hidden = true;
  try {
    const body = {choice};
    if (choice === "AWS_ACCOUNT") body.awsProfile = el("profile").value.trim() || null;
    const result = await api("/choice", body);
    if (result.status === "READY" || result.reasonCode === "OPT_OUT") {
      el("result").textContent = result.awsAccountId ? `Sharing is saved for AWS account ${result.awsAccountId}. You can close this page.` :
        result.reasonCode === "OPT_OUT" ? "No usage data will be sent. You can close this page." : "Anonymous sharing is saved. You can close this page.";
      document.querySelectorAll("button").forEach(button => {button.disabled = true;});
    } else {
      const messages = {
        SIGN_IN_REQUIRED: "Your AWS sign-in needs attention. Account sharing remains pending.",
        SDK_UNAVAILABLE: "Install the account helper dependencies as described in the telemetry README, then try again.",
        CHOICE_CHANGED: "Your choice changed during setup. Open sharing choices again to continue.",
        CHOICE_EXPIRED: "This page has expired. Open sharing choices again to continue.",
      };
      el("result").textContent = messages[result.reasonCode] || "Your account could not be checked. You can retry or choose another sharing mode.";
      el("sign-in-help").hidden = result.status !== "SIGN_IN_REQUIRED";
    }
  } catch (_) {
    el("result").textContent = "The page is unavailable. Open sharing choices again; your work can continue.";
  }
}
el("account").addEventListener("click", () => choose("AWS_ACCOUNT"));
el("anonymous").addEventListener("click", () => choose("ANONYMOUS"));
el("opt-out").addEventListener("click", () => choose("OPT_OUT"));
api("/state").then(state => {
  el("anonymous-notice").textContent = state.anonymousNotice;
  el("anonymous").disabled = false;
  el("account-section").hidden = !state.accountAvailable;
  el("account-unavailable").hidden = state.accountAvailable;
  el("account").disabled = !state.accountAvailable;
  el("account-notice").textContent = state.accountNotice || "";
  el("selected-account").textContent = state.selectedAccount ? `Current selected account: ${state.selectedAccount}` : "";
  el("profile").value = state.selectedProfile || "";
  el("result").textContent = "Select a choice. Closing this page leaves your current choice unchanged.";
}).catch(() => { el("result").textContent = "The page is unavailable. Your work can continue without sharing."; });
