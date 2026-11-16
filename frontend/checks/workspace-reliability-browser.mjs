// Additional opt-in journeys for an owned synthetic browser context. No runner,
// live URL, provider, grant or budget is created/changed by importing this file.
// Run chunk cases in fresh contexts, before opening that lazy view. A failed
// React.lazy import stays failed for that page; recovery returns to working UI.
export const RELIABILITY_JOURNEYS = Object.freeze(["optional-settings", "optional-prompts", "projects-initial-failure", "prompts-initial-failure", "settings-search", "composer-layout", "public-routes"]);
export const PUBLIC_ROUTE_CASES = Object.freeze([
  { path: "/", name: "workspace", heading: "What would you like to explore?", content: "Ask about your data.", account: true },
  { path: "/settings", name: "settings", heading: "Settings", content: "Search settings", account: true },
  { path: "/privacy", name: "privacy", heading: "Privacy Policy", content: "Information we process" },
  { path: "/terms", name: "terms", heading: "Terms of Service", content: "Accounts and access" },
  { path: "/signin", name: "signin", heading: "Welcome back", content: "Sign in to your AQUA workspace." },
  { path: "/register", name: "register", heading: "Create your workspace", content: "Start with your email." },
  { path: "/forgot-password", name: "forgot-password", heading: "Reset your password", content: "Enter your email address" },
  { path: "/check-email", name: "check-email", heading: "Check your inbox", content: "If this address is eligible" },
  { path: "/registration-sent", name: "registration-sent", heading: "Verify your email", content: "If this address is eligible" },
  { path: "/verify-email", name: "verify-email-missing-proof", heading: "Request a new link", content: "This link is missing, invalid" },
  { path: "/reset-password", name: "reset-password-missing-proof", heading: "Request a new link", content: "This link is missing, invalid" },
  ...["password_add", "email_change_new", "email_change_old"].map((action) => ({ path: "/account-action/" + action, name: "account-action-" + action.replaceAll("_", "-"), heading: "Return to your account action", content: "Opening this link makes no account change." })),
]);
// Fixed GET-only fixture faults. Neither URL arguments nor mutations can select
// a target; default and existing notification journeys receive no fault.
export function reliabilityFault(journey, pathname, method) {
  if (method !== "GET" || typeof pathname !== "string") return null;
  if (journey === "optional-settings" && /^\/assets\/SettingsShell-[A-Za-z0-9_-]+\.js$/.test(pathname)
    || journey === "optional-prompts" && /^\/assets\/PromptLibraryDialog-[A-Za-z0-9_-]+\.js$/.test(pathname)) return "chunk";
  if (journey === "projects-initial-failure" && pathname === "/api/v1/projects"
    || journey === "prompts-initial-failure" && pathname === "/api/v1/me/saved-prompts") return "list";
  return null;
}
export async function optionalViewFailure(ctx, kind) {
  if (!["settings", "prompts"].includes(kind)) throw Error("optional_view_kind_invalid");
  const before = ctx.queryCount();
  await ctx.fill(".opal-composer textarea", "Synthetic unsent download-recovery draft");
  await ctx.evaluate("window.__recoveryComposer=document.querySelector('.opal-composer textarea');true");
  try {
    if (kind === "settings") {
      await ctx.click('[aria-label="Account menu"]');
      await ctx.waitFor("Boolean(document.querySelector('[role=menu][aria-label=\"Your account\"]'))", "settings_account_menu_ready");
      await ctx.evaluate("(()=>{const el=Array.from(document.querySelectorAll('[role=menuitem]')).find(el=>el.getClientRects().length&&!el.closest('[hidden],[inert]')&&el.querySelector('span')?.textContent==='Settings');if(!el||el.disabled)throw Error();el.click();return true})()");
      await ctx.waitFor("Boolean(document.querySelector('[aria-label=\"Settings unavailable\"]'))", "settings_download_failure_contained");
      await ctx.clickText("Back to workspace", '[aria-label="Settings unavailable"] button');
    } else {
      await ctx.click('[aria-label="Saved prompts"]');
      await ctx.waitFor("[...document.querySelectorAll('dialog[open] h2')].some(el=>el.textContent==='Saved prompts unavailable')", "prompt_download_failure_contained");
      await ctx.clickText("Close saved prompts", "dialog[open] button");
    }
    await ctx.waitFor("document.querySelector('.opal-composer textarea')?.getClientRects().length>0", "workspace_recovered_after_optional_failure");
    await ctx.check("A failed optional view preserves the same account composer and unsent text", "document.querySelector('.opal-composer textarea')===window.__recoveryComposer&&document.querySelector('.opal-composer textarea').value==='Synthetic unsent download-recovery draft'&&document.activeElement.closest('.opal-workspace')!==null");
    if (ctx.queryCount() !== before) throw Error("optional_failure_submitted_analysis");
    await ctx.screenshot("optional-" + kind + "-failure-recovered");
  } finally {
    await ctx.evaluate("delete window.__recoveryComposer;true");
  }
}

// Use a fresh P08 fixture and its two fixed 51-row answers. These are two of the
// unchanged twelve fake jobs, never real provider work or a raised fixture cap.
export async function selectedResultTableReset(ctx, submit) {
  if (typeof submit !== "function") throw Error("fixed_synthetic_submit_required");
  await submit("P08 chart oversized");
  await ctx.waitFor("Boolean(document.querySelector('.visual-pane .financial-table__pagination'))", "first_paginated_result_ready");
  await ctx.clickText("Next rows", ".visual-pane button");
  await ctx.clickText("Show full precision", ".visual-pane button");
  await ctx.evaluate("document.querySelector('.visual-pane .sort-button').click();true");
  await ctx.check("The first selected result has exercised page, sort and precision state", "document.querySelector('.visual-pane .financial-table__pagination').textContent.includes('Page 2 of')&&Boolean(document.querySelector('.visual-pane th[aria-sort=ascending]'))&&[...document.querySelectorAll('.visual-pane button')].some(el=>el.textContent==='Use display precision')");
  await submit("P08 chart oversized");
  await ctx.waitFor("document.querySelectorAll('.conversation .visual-result-open').length>=2", "second_result_selected");
  const reset = "document.querySelector('.visual-pane .financial-table__pagination').textContent.includes('Page 1 of')&&!document.querySelector('.visual-pane th[aria-sort=ascending],.visual-pane th[aria-sort=descending]')&&[...document.querySelectorAll('.visual-pane button')].some(el=>el.textContent==='Show full precision')";
  await ctx.waitFor(reset, "new_result_table_state_reset");
  await ctx.check("A newly selected result starts at page one with fresh sort and precision state", reset);
  await ctx.clickText("Next rows", ".visual-pane button");
  await ctx.evaluate("Array.from(document.querySelectorAll('.conversation .visual-result-open')).at(-2).click();true");
  await ctx.waitFor("document.querySelector('.visual-pane .financial-table__pagination').textContent.includes('Page 1 of')", "earlier_result_table_state_reset");
  await ctx.check("Explicitly selecting an earlier owned result also resets table paging", "document.querySelector('.visual-pane .financial-table__pagination').textContent.includes('Page 1 of')");
  await ctx.screenshot("selected-result-table-reset");
}

// The runner supplies a closed GET-only synthetic failure before login/opening
// the list, then restores that same fixture route. No mutation is replayed.
export async function personalListRetry(ctx, kind, restoreRead, expectEmpty = true) {
  if (!["projects", "prompts"].includes(kind) || typeof restoreRead !== "function" || typeof expectEmpty !== "boolean") throw Error("personal_list_fixture_invalid");
  const noun = kind === "projects" ? "projects" : "saved prompts";
  const scope = kind === "projects" ? ".desktop-sidebar .refined-nav-section" : "dialog[open]";
  if (kind === "prompts") await ctx.click('[aria-label="Saved prompts"]');
  const failure = kind === "projects" ? "Projects could not be loaded." : "Saved prompts could not be loaded.";
  const empty = kind === "projects" ? "No projects yet." : "No saved prompts yet.";
  await ctx.waitFor(`Array.from(document.querySelectorAll(${JSON.stringify(scope)})).some(el=>el.textContent.includes(${JSON.stringify(failure)}))`, "personal_list_failure_visible");
  await ctx.check("A failed personal list does not claim the account is empty", `Array.from(document.querySelectorAll(${JSON.stringify(scope)})).some(el=>el.textContent.includes(${JSON.stringify(failure)})&&!el.textContent.includes(${JSON.stringify(empty)}))`);
  await restoreRead(); await ctx.clickText("Retry " + noun, scope + " button");
  await ctx.waitFor(`!Array.from(document.querySelectorAll(${JSON.stringify(scope)})).some(el=>el.textContent.includes(${JSON.stringify(failure)})||el.textContent.includes('Loading ${noun}'))`, "personal_list_retry_confirmed");
  if (expectEmpty) await ctx.check("Only the successful empty read reports an empty account list", `Array.from(document.querySelectorAll(${JSON.stringify(scope)})).some(el=>el.textContent.includes(${JSON.stringify(empty)}))`);
  await ctx.screenshot("personal-" + kind + "-read-recovered");
}

export async function settingsActionSearch(ctx) {
  for (const query of ["import", "delete history"]) {
    await ctx.fill("#settings-search", query);
    await ctx.check("Operational Settings labels find Privacy without applying an action", "document.querySelector('.settings-category-section h2')?.textContent==='Privacy & data'&&!document.querySelector('.settings-content').textContent.includes('No settings match')");
  }
  await ctx.fill("#settings-search", "");
}

export async function modifiedComposerShortcut(ctx) {
  await ctx.evaluate("document.querySelector('.workspace-quick-switch').focus();true");
  const press = async (modifiers) => {
    await ctx.cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "/", code: "Slash", windowsVirtualKeyCode: 191, modifiers });
    await ctx.cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "/", code: "Slash", windowsVirtualKeyCode: 191, modifiers });
  };
  await press(0);
  await ctx.check("An unmodified printable shortcut does not move keyboard focus", "document.activeElement.matches('.workspace-quick-switch')");
  await press(2);
  await ctx.check("The modified composer shortcut still reaches the question field", "document.activeElement.matches('.opal-composer textarea')");
}

export async function measureComposerFooters(ctx, phase = "entry") {
  if (!["entry", "before-settings", "after-settings"].includes(phase)) throw Error("footer_measurement_phase_invalid");
  const measurements = [];
  for (const [width, height] of [[1440, 980], [390, 844]]) {
    await ctx.cdp.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width === 390 });
    await ctx.waitFor(`innerWidth===${width}&&innerHeight===${height}`, "footer_measurement_viewport_ready");
    await ctx.evaluate("document.fonts.ready.then(()=>true)");
    // Wait for finite transitions/FLIP animations; infinite decorations are not
    // measured and never extend the existing host/browser deadline.
    await ctx.waitFor("Array.from(document.querySelector('.opal-composer-wrap').getAnimations({subtree:true})).every(a=>!Number.isFinite(a.effect?.getComputedTiming().endTime)||!a.pending&&a.playState!=='running')", "finite_composer_animation_settled");
    const geometry = await ctx.evaluate(`(async()=>{
      await document.fonts.ready;await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      const box=selector=>{const el=document.querySelector(selector),r=el?.getBoundingClientRect();if(!el||!r||!el.getClientRects().length)throw Error();const s=getComputedStyle(el);return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height,font_size:parseFloat(s.fontSize),line_height:parseFloat(s.lineHeight)};};
      const hint=box('.composer-hint'),disclaimer=box('.opal-disclaimer');
      return {viewport:{width:innerWidth,height:innerHeight},hint,disclaimer,vertical_gap:disclaimer.top-hint.bottom,overlap_width:Math.max(0,Math.min(hint.right,disclaimer.right)-Math.max(hint.left,disclaimer.left)),overlap_height:Math.max(0,Math.min(hint.bottom,disclaimer.bottom)-Math.max(hint.top,disclaimer.top)),finite_composer_animations_running:Array.from(document.querySelector('.opal-composer-wrap').getAnimations({subtree:true})).filter(a=>Number.isFinite(a.effect?.getComputedTiming().endTime)&&(a.pending||a.playState==='running')).length};
    })()`);
    if (![geometry.vertical_gap, geometry.overlap_width, geometry.overlap_height].every(Number.isFinite)
      || geometry.finite_composer_animations_running !== 0 || ![geometry.hint, geometry.disclaimer].every(box=>box.width>0&&box.height>0&&[box.left,box.right,box.top,box.bottom,box.font_size,box.line_height].every(Number.isFinite))) throw Error("footer_geometry_invalid");
    measurements.push({ phase, ...geometry });
    await ctx.screenshot(`composer-footer-${phase}-${width}x${height}`);
  }
  return measurements;
}

export async function publicRouteWalkthrough(ctx, selectFixtureAccount) {
  const inventory = [];
  for (const [width, height] of [[1440, 980], [320, 844]]) {
    await ctx.cdp.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width === 320 });
    for (const route of PUBLIC_ROUTE_CASES) {
      selectFixtureAccount(route.account === true);
      await ctx.navigate(route.path);
      const heading = `Array.from(document.querySelectorAll('main h1')).find(el=>el.getClientRects().length&&!el.closest('[hidden],[inert]')&&el.textContent===${JSON.stringify(route.heading)})`;
      await ctx.waitFor(`location.pathname===${JSON.stringify(route.path)}&&Boolean(${heading})`, "public_route_heading_ready");
      await ctx.waitFor("!document.querySelector('.auth-google[aria-busy=true]')&&!document.querySelector('[data-testid=password-auth-submit]:disabled')", "public_route_initial_reads_settled");
      await ctx.evaluate("document.fonts.ready.then(()=>true)");
      await ctx.check("The route renders its expected visible main heading and content", `Boolean(${heading})&&document.body.innerText.includes(${JSON.stringify(route.content)})`);
      await ctx.check("The route has no horizontal page overflow", "document.documentElement.scrollWidth<=innerWidth+1");
      const navigation = route.path === "/" ? "button[aria-label=\"Open navigation\"],.desktop-sidebar [aria-label=\"Account menu\"]"
        : route.path === "/settings" || route.path.startsWith("/account-action/") ? "button"
          : route.path === "/privacy" || route.path === "/terms" ? ".legal-page__nav a" : ".auth-card a[href]";
      await ctx.check("The route has reachable keyboard back or local navigation", `(()=>{const el=Array.from(document.querySelectorAll(${JSON.stringify(navigation)})).find(el=>el.getClientRects().length&&!el.closest('[hidden],[inert]')&&!el.disabled);if(!el)return false;el.scrollIntoView({block:'center'});el.focus();const r=el.getBoundingClientRect();return document.activeElement===el&&r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1})()`);
      if (route.path.startsWith("/account-action/")) {
        await ctx.check("A mail landing is inert and exposes no proof or mutation form", "!document.querySelector('form,input,.opal-workspace')&&!location.search&&!location.hash");
        await ctx.check("Mail handoff navigation retains the approved touch target", "(()=>{const r=document.querySelector('.auth-card button').getBoundingClientRect();return r.width>=43.9&&r.height>=43.9})()");
      }
      await ctx.evaluate("window.scrollTo(0,0);document.querySelector('.settings-page')?.scrollTo(0,0);true");
      await ctx.screenshot(`route-${route.name}-${width}px`, true);
      inventory.push({ path: route.path, width, height, heading: route.heading });
      if (route.path === "/terms") {
        // Exercise the in-body SPA policy link from a scrolled position, rather
        // than checking two unrelated direct page loads.
        await ctx.evaluate("(()=>{const el=document.querySelector('.legal-page__content>p a[href=\"/privacy\"]');if(!el)throw Error();el.scrollIntoView({block:'center'});el.click();return true})()");
        await ctx.waitFor("location.pathname==='/privacy'&&document.querySelector('#legal-heading')?.textContent==='Privacy Policy'", "policy_switch_completed");
        await ctx.check("Switching policy pages makes the new heading visible", "(()=>{const r=document.querySelector('#legal-heading').getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight+1})()");
      }
    }
  }
  return inventory;
}
