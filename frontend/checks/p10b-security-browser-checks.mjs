const q = JSON.stringify;
export const SECURITY_SCENARIOS = new Set(["password", "revoke-current", "revoke-other", "revoke-all", "lost-other", "verification-failure"]);
const dialog = ".account-security-dialog[open]";
const phase = value => `document.querySelector('[data-account-security-phase]')?.dataset.accountSecurityPhase===${q(value)}`;

export async function runSecurityChecks(ctx, { scenario, email, password, newPassword }) {
  if (!SECURITY_SCENARIOS.has(scenario)) throw Error("security_scenario_invalid");
  const { evaluate, check, waitFor, click, fill, clickText } = ctx;
  const sessionCookies = async () => {
    const cookies = (await ctx.cdp.send("Network.getCookies", { urls: [ctx.origin] })).cookies;
    for (const cookie of cookies) ctx.secrets.add(cookie.value);
    const sessions = cookies.filter(cookie => cookie.name === "__Host-aqua_session");
    if (sessions.length !== 1 || !sessions[0].secure || !sessions[0].httpOnly || sessions[0].path !== "/" || sessions[0].sameSite !== "Lax"
      || sessions[0].domain !== "aqua-browser.example.test") throw Error("secure_session_cookie_invalid");
    return sessions[0].value;
  };
  const first = await ctx.rawRequest("GET", "/api/auth/me"), account = JSON.parse(first.body);
  if (first.status !== 200 || account.can_query !== false) throw Error("account_grant_boundary_invalid");
  const originalCookie = await sessionCookies();
  // A second real login creates another active session. No row is injected and
  // no grant, budget, expiry or server clock is modified for this test.
  const bootstrap = await ctx.rawRequest("GET", "/api/v1/auth/bootstrap?action=login");
  if (bootstrap.status !== 200) throw Error("second_session_bootstrap_failed");
  const csrf = JSON.parse(bootstrap.body).csrf_token; ctx.secrets.add(csrf);
  const login = await ctx.rawRequest("POST", "/api/v1/auth/password-login", { email, password }, csrf);
  if (login.status !== 200 || JSON.parse(login.body).user.id !== account.user.id) throw Error("second_session_login_failed");
  const currentCookie = await sessionCookies();
  if (currentCookie === originalCookie) throw Error("second_session_not_distinct");
  const observer = `(()=>{
    const perform=window.fetch.bind(window);window.__securityAudit=[];window.__securityHoldAuth=false;window.__securityLoseCommit=false;
    window.fetch=(resource,options={})=>{
      const url=new URL(typeof resource==='string'?resource:resource.url,location.href),method=(options.method||'GET').toUpperCase();
      const security=url.origin===location.origin&&/^\\/api\\/v1\\/me\\/(?:reauth-challenges|reauth\\/password|password|session-revocations|sessions\\/[a-f0-9-]+\\/revocations)$/.test(url.pathname);
      if(security)window.__securityAudit.push({route:url.pathname,method});
      return perform(resource,options).then(response=>{
        if(url.origin===location.origin&&url.pathname==='/api/auth/me'&&window.__securityHoldAuth){window.__securityHoldAuth=false;return new Promise(resolve=>{window.__securityReleaseAuth=()=>{delete window.__securityReleaseAuth;resolve(response);};});}
        if(security&&window.__securityLoseCommit&&response.status===200&&(/\\/revocations$/.test(url.pathname)||url.pathname.endsWith('/session-revocations')||url.pathname.endsWith('/password')&&!url.pathname.endsWith('/reauth/password'))){window.__securityLoseCommit=false;throw new TypeError('Synthetic lost security response');}
        return response;
      });
    };return true;
  })()`;
  await ctx.cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: observer });
  await ctx.navigate("/settings");
  await waitFor("document.querySelector('#settings-field-accent')?.disabled===false", "security_settings_ready");
  await check("Security controls use a real secure reserved origin and the requested shell", `isSecureContext&&location.origin==='https://aqua-browser.example.test'&&document.querySelector('.opal-workspace')?.dataset.uiShell===${q(process.env.AQUA_P05_EXPECTED_SHELL || "opal")}`);
  await check("Appearance performs no security action or verification", "window.__securityAudit.length===0");
  await click('[data-settings-category="account"]');
  await waitFor("Boolean(document.querySelector('[data-account-profile]'))", "security_account_profile_ready");
  await check("Password changes stay disabled until actual linked methods are requested", "document.querySelector('[data-account-change-password]').disabled===true&&window.__securityAudit.length===0");
  await click("[data-account-load-methods]"); await waitFor("Boolean(document.querySelector('[data-account-methods]'))", "security_methods_ready");
  await check("Dedicated secure fixture exposes implemented password actions after actual method review", "document.querySelector('[data-account-change-password]').disabled===false");
  await click("[data-account-load-sessions]"); await waitFor("document.querySelectorAll('.account-session').length===2", "two_real_sessions_ready");
  await check("Current and other sessions remain distinct without a data grant", "document.querySelectorAll('[data-account-revoke-session=current]').length===1&&document.querySelectorAll('[data-account-revoke-session=other]').length===1");
  const launch = scenario === "password" ? "[data-account-change-password]" : scenario === "revoke-all" ? "[data-account-revoke-all]"
    : scenario === "revoke-current" ? "[data-account-revoke-session=current]" : "[data-account-revoke-session=other]";
  await click(launch); await waitFor(`Boolean(document.querySelector(${q(dialog)}))`, "security_action_open");
  await check("Initial destructive dialog focuses Cancel and performs no security request", "document.activeElement?.textContent==='Cancel'&&window.__securityAudit.length===0");
  await clickText("Cancel", dialog + " button");
  await check("Cancel before verification leaves both real sessions and makes no mutation", `!document.querySelector(${q(dialog)})&&document.querySelectorAll('.account-session').length===2&&window.__securityAudit.length===0`);
  await click(launch);
  const privateMarkup = async label => {
    await check(label, `(()=>{const values=${q([...ctx.secrets])},stored=JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)]),html=document.documentElement.outerHTML;return !location.hash&&values.every(value=>typeof value==='string'&&!stored.includes(value)&&!html.includes(value))})()`);
  };
  const verify = async value => {
    await fill("[data-account-current-password]", value);
    await privateMarkup("Entered current password stays out of serialized markup and persistent storage");
    await click("[data-account-verify-password]");
  };
  if (scenario === "verification-failure") {
    const incorrect = "Synthetic incorrect current password 88"; ctx.secrets.add(incorrect);
    await verify(incorrect);
    await waitFor(phase("verify") + "&&Boolean(document.querySelector('.account-security-dialog [role=alert]'))", "failed_verification_retained");
    await check("Failed password verification clears the field and cannot expose a confirmation action", "document.querySelector('[data-account-current-password]').value===''&&!document.querySelector('[data-account-confirm-security]')&&window.__securityAudit.length===2");
  } else {
    await verify(password); await waitFor(phase("confirm"), "first_proof_ready");
    await check("Successful verification clears the current password before final confirmation", "!document.querySelector('[data-account-current-password]')&&Boolean(document.querySelector('[data-account-confirm-security]'))");
    await evaluate("(()=>{window.__securityHoldAuth=true;const channel=new BroadcastChannel('aqua-session-events');channel.postMessage({type:'changed'});channel.close();return true})()");
    await waitFor("typeof window.__securityReleaseAuth==='function'", "security_real_auth_refresh_held");
    await waitFor("Boolean(document.querySelector('.opal-workspace')?.closest('[hidden],[inert]'))&&!document.querySelector('.account-security-dialog[open]')", "security_modal_hidden_with_authority");
    await check("Pending real auth authority removes the security dialog from the native top layer", "!document.querySelector('.account-security-dialog[open]')");
    await evaluate("window.__securityReleaseAuth()");
    await waitFor(phase("verify") + "&&Boolean(document.querySelector('.account-security-dialog[open]'))&&document.querySelector('[data-account-current-password]')?.disabled===false", "security_authority_restored_without_proof");
    await check("Same-owner auth restoration discards the earlier proof and requires fresh password verification", "document.querySelector('[data-account-current-password]').value===''&&!document.querySelector('[data-account-confirm-security]')&&window.__securityAudit.length===2");
  }
  await verify(password); await waitFor(phase("confirm"), "fresh_target_bound_proof_ready");
  const cookies = (await ctx.cdp.send("Network.getCookies", { urls: [ctx.origin] })).cookies;
  const binding = cookies.filter(cookie => cookie.name === "__Host-aqua_account_action");
  if (binding.length !== 1 || !binding[0].secure || !binding[0].httpOnly || binding[0].path !== "/" || binding[0].sameSite !== "Lax" || binding[0].domain !== "aqua-browser.example.test"
    || binding[0].expires <= Date.now() / 1000 || binding[0].expires > Date.now() / 1000 + 305) throw Error("action_binding_cookie_invalid");
  ctx.results.push({ check: "Real Chrome stores the action binding as host-only Secure HttpOnly SameSite-Lax", passed: true });
  await check("HTTP-only session and action cookies are unavailable to JavaScript", "!document.cookie.includes('__Host-aqua_session=')&&!document.cookie.includes('__Host-aqua_account_action=')");
  await check("Fresh verification is followed by a separate explicit confirmation with Cancel available", "document.activeElement?.textContent==='Cancel'&&[...document.querySelectorAll('.account-security-dialog button')].some(button=>button.textContent==='Cancel'&&!button.disabled)&&window.__securityAudit.length===4");
  const tab = async shift => {
    await ctx.cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, modifiers: shift ? 8 : 0 });
    await ctx.cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, modifiers: shift ? 8 : 0 });
  };
  await evaluate("document.querySelector('[data-account-confirm-security]').focus()"); await tab(false);
  await check("Security confirmation wraps forward keyboard focus within the native dialog", "document.activeElement===[...document.querySelectorAll('.account-security-dialog input,.account-security-dialog button')].find(element=>!element.disabled)");
  await tab(true);
  await check("Security confirmation wraps reverse keyboard focus within the native dialog", "document.activeElement===document.querySelector('[data-account-confirm-security]')");
  const baseText = await evaluate("parseFloat(getComputedStyle(document.querySelector('[data-account-confirm-security]')).fontSize)");
  await ctx.cdp.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 900, deviceScaleFactor: 1, mobile: false });
  await evaluate("document.documentElement.style.fontSize='200%'");
  await check("Security confirmation reflows at 320px with actual control text doubled", `(()=>{const d=document.querySelector('.account-security-dialog[open]').getBoundingClientRect(),b=document.querySelector('[data-account-confirm-security]');return d.left>=0&&d.right<=innerWidth+1&&document.documentElement.scrollWidth<=innerWidth+1&&parseFloat(getComputedStyle(b).fontSize)>=${baseText}*1.99})()`);
  await ctx.screenshot("p10b-" + scenario + "-mobile-confirm");
  await evaluate("document.documentElement.style.fontSize=''");
  await ctx.cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await privateMarkup("Proofs and passwords are absent from URLs, rendered markup and persistent browser storage");
  await ctx.screenshot("p10b-" + scenario + "-confirm");
  if (scenario === "password") {
    await fill("[data-account-new-password]", newPassword);
    await privateMarkup("Entered new password stays out of serialized markup and persistent storage");
    await fill("[data-account-confirm-password]", newPassword);
    await privateMarkup("Entered password confirmation stays out of serialized markup and persistent storage");
  }
  if (scenario === "lost-other") await evaluate("window.__securityLoseCommit=true");
  await click("[data-account-confirm-security]");
  if (["revoke-other", "verification-failure"].includes(scenario)) {
    await waitFor(phase("done"), "other_session_revocation_confirmed");
    await check("Confirmed other-session revocation removes only that session and keeps current access", "document.querySelectorAll('.account-session').length===1&&document.querySelectorAll('[data-account-revoke-session=other]').length===0");
    const me = await ctx.rawRequest("GET", "/api/auth/me"); if (me.status !== 200 || JSON.parse(me.body).user.id !== account.user.id) throw Error("current_session_not_preserved");
  } else if (scenario === "lost-other") {
    await waitFor(phase("uncertain"), "lost_security_response_uncertain");
    await check("A lost real commit reply cannot claim success or replay its proof", "!document.querySelector('[data-account-confirm-security]')&&window.__securityAudit.length===5&&document.querySelectorAll('.account-session').length===2");
    await click("[data-account-check-security]"); await waitFor(phase("review"), "lost_security_response_checked");
    await check("Explicit GET reconciliation reports an inactive session without crediting the uncertain mutation", "document.querySelector('.account-security-dialog').textContent.includes('does not confirm which action')&&document.querySelectorAll('.account-session').length===1&&window.__securityAudit.length===5&&!document.querySelector('[data-account-confirm-security]')");
  } else {
    await waitFor("!document.querySelector('.account-security-dialog[open]')&&document.querySelector('#auth-password')?.disabled===false", "confirmed_current_authority_ended");
    const me = await ctx.rawRequest("GET", "/api/auth/me"); if (me.status !== 401) throw Error("current_session_still_valid");
    ctx.results.push({ check: "Only the confirmed server mutation ends cached current authority and requires sign-in", passed: true });
  }
  const originalStatus = await ctx.probeCopiedSession(originalCookie), currentStatus = await ctx.probeCopiedSession(currentCookie);
  const originalExpected = scenario === "revoke-current" ? 200 : 401, currentExpected = ["password", "revoke-current", "revoke-all"].includes(scenario) ? 401 : 200;
  if (originalStatus !== originalExpected || currentStatus !== currentExpected) throw Error("copied_session_revocation_scope_invalid");
  ctx.results.push({ check: "Copied real session cookies obey the exact confirmed revocation scope", passed: true });
  if (scenario === "password") {
    const notice = await ctx.bridge.send("security_mail_status");
    if (notice.purpose !== "password_changed" || notice.body_exposed !== false || notice.real_provider_calls !== 0 || notice.failed !== 0 || notice.queued + notice.completed < 1) throw Error("mandatory_security_notice_unconfirmed");
    await fill("#auth-email", email); await fill("#auth-password", newPassword); await click("[data-testid=password-auth-submit]");
    await waitFor("Boolean(document.querySelector('.opal-workspace'))", "changed_password_login_confirmed");
    const me = await ctx.rawRequest("GET", "/api/auth/me"); if (me.status !== 200 || JSON.parse(me.body).user.id !== account.user.id || JSON.parse(me.body).can_query !== false) throw Error("changed_password_login_invalid");
    ctx.results.push({ check: "The changed password signs in through the real login flow without granting analytical access", passed: true });
    ctx.results.push({ check: "Required encrypted security notice is queued or completed only by the fake mail worker", passed: true });
  }
  await check("Exactly one explicit mutation follows four verification requests without automatic replay", "window.__securityAudit.length===5&&window.__securityAudit.filter(item=>!item.route.includes('/reauth')).length===1");
  await ctx.screenshot("p10b-" + scenario + "-result");
  return { scenario, actual_provider_calls: 0, fake_jobs_requested: 0, fixture_dataset_grant: false, security_post_put_attempts: await evaluate("window.__securityAudit.length"),
    copied_session_authority_probes: 2, server_quota_clock_or_limit_changes: 0, secure_origin_mode: "cdp_fulfilled_reserved_https_origin", dns_socket_tls_transport_tested: false };
}
