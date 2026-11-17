import assert from "node:assert/strict";
import { ensureNavigation } from "./homepage-browser-actions.mjs";
import { RESULT_CHAT_TITLES, RESULT_BROWSER_GOLD, RESULT_BROWSER_FIXTURE_SHA256 } from "./result-companion-browser-fixture.mjs";

export const resultCompanionKey = (dispatch, key) => dispatch(key, 0, key === "Enter" ? "\r" : undefined);
export const resultCompanionDoubledText = (normal, enlarged) => Number.isFinite(normal) && Number.isFinite(enlarged)
  && normal >= 14 && Math.abs(enlarged - normal * 2) <= 0.1;

// Only the opt-in P05 branch invokes this journey. Its inherited caps, actual
// BrowserPipe, browser cleanup and failure rules stay unchanged.
export async function runResultCompanionChecks(ctx, { emailA, emailB, result }) {
  const { fixture, check, click, clickText, fill, waitFor, evaluate, navigate, signIn, viewport, screenshot } = ctx;
  const key = value => resultCompanionKey(ctx.key, value), quote = JSON.stringify;
  const pause = () => new Promise(resolve => setTimeout(resolve, 80));
  const selectChat = async index => {
    await ensureNavigation(ctx);
    await waitFor(`Boolean([...document.querySelectorAll('button')].find(el=>el.textContent.trim()===${quote(RESULT_CHAT_TITLES[index])}))`, "result_saved_chat_ready");
    await clickText(RESULT_CHAT_TITLES[index]);
    await waitFor(`document.querySelector('.breadcrumb strong')?.textContent===${quote(RESULT_CHAT_TITLES[index])}&&Boolean(document.querySelector('[data-understand-result]'))`, "result_saved_reply_loaded");
  };
  const open = async () => {
    await evaluate("document.querySelector('[data-understand-result]').focus();true"); await key("Enter");
    await waitFor("Boolean(document.querySelector('dialog[open]'))", "result_dialog_open");
  };
  const close = async () => { await click("[data-close-result-companion]"); await waitFor("!document.querySelector('dialog[open]')", "result_dialog_closed"); };
  const ready = () => waitFor("Boolean(document.querySelector('[data-result-facts]'))", "result_facts_ready");
  const held = async (count = 1) => {
    const until = performance.now() + 5500;
    while (result.pending.length < count && performance.now() < until) await pause();
    assert.equal(result.pending.length, count, "result_bounded_held_reads");
  };
  const column = async index => {
    await evaluate("document.querySelector('[data-result-column]').focus();true"); await key("Home");
    if (index === 1) await key("ArrowDown");
    await waitFor(`document.querySelector('[data-result-column]')?.value===${quote(String(index))}`, "result_native_field_selection");
  };
  const originalNodes = () => check("result panel preserves the existing saved table and composer nodes",
    "document.querySelector('.conversation table')===window.__resultTable&&document.querySelector('.opal-composer textarea')===window.__resultComposer");
  const prepare = async () => { await click("[data-result-intent=missing_values]"); await click("[data-companion-guide-prepare]");
    await waitFor("document.querySelector('[data-result-draft]')?.value.includes('Measure:')&&!document.querySelector('[data-result-apply]').disabled", "result_guided_preview"); };
  fixture.email = null; fixture.canQuery = true; await viewport(1440, 960); await navigate("/signin"); await signIn(emailA); await selectChat(0);
  const queries = fixture.queryCount(); assert.equal(queries, 0);
  await fill(".opal-composer textarea", "Unsent result companion sample draft");
  await evaluate("window.__resultComposer=document.querySelector('.opal-composer textarea');window.__resultTable=document.querySelector('.conversation table');true");

  result.enabled = false; await open();
  await waitFor("document.querySelector('.result-companion [role=alert]')?.textContent.includes('unavailable')", "result_optional_disabled");
  await close(); await originalNodes(); result.enabled = true;
  await open(); await ready();
  await check("numeric facts preserve exact saved values and original row citations", `(()=>{const r=document.querySelector('[data-result-facts]');return r.textContent.includes(${quote(RESULT_BROWSER_GOLD.maximum)})&&r.textContent.includes(${quote(RESULT_BROWSER_GOLD.minimum)})&&r.textContent.includes('2 returned rows have this value')&&r.textContent.includes('Saved row 2, field 1')&&r.textContent.includes('Saved row 4, field 1')&&r.textContent.includes('4 returned rows')&&r.textContent.includes('1 saved value is missing')})()`);
  await check("subset checks expose unknown units source freshness and scope without claiming business causes", "(()=>{const r=document.querySelector('[data-result-facts]');return r.textContent.includes('This result is truncated')&&r.textContent.includes('Unit unspecified')&&r.textContent.includes('generation time is not source freshness')&&r.textContent.includes('Filters and aggregation')&&r.textContent.includes('before table sorting or paging')&&!r.textContent.includes('USD')&&!r.querySelector('a,img,script,form')})()");
  await originalNodes(); await screenshot("result-companion-desktop-exact-facts");
  await column(1); await waitFor("document.querySelector('[data-result-facts]')?.textContent.includes('No numerical range is provided for this text field')", "result_text_field_ready");
  await check("selecting a text field replaces numeric facts without coercing numeric-looking strings", "document.querySelector('[data-result-facts]').textContent.includes('0 saved values are missing')&&!document.querySelector('.result-companion__value')&&!document.querySelector('[data-result-intent=compare_field]')");
  await column(0); await ready(); await prepare();
  await check("guided follow-up preview preserves explicit unknowns and leaves composer untouched", "(()=>{const q=document.querySelector('[data-result-draft]').value;return q.includes('Measure: Count rows with a missing value')&&['Grouping','Time period','Filters'].every(label=>q.includes(label+': Not specified.'))&&q.includes('Do not invent omitted details')&&window.__resultComposer.value==='Unsent result companion sample draft'&&!document.querySelector('.result-companion form')})()");
  await fill("[data-companion-guide-field=grouping]", "User supplied sample category");
  await check("editing guide fields disables apply until another explicit preparation", "document.querySelector('[data-result-apply]').disabled&&!document.querySelector('[data-result-draft]').value.includes('User supplied sample category')");
  await click("[data-companion-guide-prepare]"); await fill("[data-result-draft]", "My explicitly reviewed sample follow-up with a verified definition.");
  // An out-of-band existing input callback models a concurrent composer update;
  // it is not a physical action through the native modal's inert background.
  await fill(".opal-composer textarea", "Newer draft must survive"); await click("[data-result-apply]");
  await waitFor("document.querySelector('.result-companion [role=alert]')?.textContent.includes('text was preserved')", "result_composer_conflict");
  await close(); await check("a draft conflict never overwrites the newer composer", "window.__resultComposer.value==='Newer draft must survive'");
  await open(); await ready(); await prepare();
  await fill("[data-result-draft]", "My explicitly reviewed sample follow-up with a verified definition.");
  await click("[data-result-apply]"); await waitFor("!document.querySelector('dialog[open]')", "result_explicit_apply");
  await check("explicit Apply updates only the existing composer draft and keeps normal Send separate", "document.querySelector('.opal-composer textarea')===window.__resultComposer&&window.__resultComposer.value==='My explicitly reviewed sample follow-up with a verified definition.'");
  assert.equal(fixture.queryCount(), queries, "result_prepare_edit_apply_never_submit_analysis"); await originalNodes();

  await open(); await ready(); await prepare();
  const normalFont = await evaluate("parseFloat(getComputedStyle(document.querySelector('.result-companion > p')).fontSize)");
  await viewport(320, 844, true); await evaluate("document.querySelector('.opal-workspace').style.setProperty('--pref-text-scale','2');document.querySelector('.result-companion-dialog').scrollTop=0;true");
  result.geometry = await evaluate("(()=>{const d=document.querySelector('.result-companion-dialog'),r=d.getBoundingClientRect(),n=v=>Math.round(v*100)/100;return {width:innerWidth,left:n(r.left),right:n(r.right),client:d.clientWidth,scroll:d.scrollWidth,font:n(parseFloat(getComputedStyle(d.querySelector('.result-companion > p')).fontSize)),controls:[...d.querySelectorAll('button:not(:disabled),select,input,textarea')].slice(0,20).map(el=>({height:n(el.getBoundingClientRect().height),labels:el.labels?.length??null}))}})()");
  assert.equal(resultCompanionDoubledText(normalFont, result.geometry.font), true, "result_actual_text_doubled");
  await check("320px doubled text keeps exact facts and labeled 44px controls within the dialog", "(()=>{const d=document.querySelector('.result-companion-dialog'),r=d.getBoundingClientRect();return r.left>=-1&&r.right<=innerWidth+1&&d.scrollWidth<=d.clientWidth+1&&[...d.querySelectorAll('button:not(:disabled),select,input,textarea')].every(el=>el.getBoundingClientRect().height>=43.5)&&d.querySelector('select').labels.length===1})()");
  await screenshot("result-companion-320-double-text");
  await evaluate("document.querySelector('.result-companion details summary').focus();true"); await key("Tab");
  await check("native source disclosure advances to the next follow-up control by Tab", "document.activeElement===document.querySelector('[data-result-intent=verify_scope]')");
  await evaluate("document.querySelector('[data-close-result-companion]').focus();true"); await key("Tab");
  await check("native modal Tab wraps from Close to the first field selector", "document.activeElement===document.querySelector('[data-result-column]')");
  let reachable = false;
  for (let i = 0; i < 24; i++) { if (await evaluate("document.activeElement===document.querySelector('[data-close-result-companion]')")) { reachable = true; break; } await key("Tab"); }
  assert.equal(reachable, true, "result_close_reachable_by_bounded_keyboard_tabs");
  await screenshot("result-companion-320-keyboard-close"); await key("Escape"); await waitFor("!document.querySelector('dialog[open]')", "result_keyboard_escape");
  await viewport(1440, 960); await evaluate("document.querySelector('.opal-workspace').style.setProperty('--pref-text-scale','1');true");
  await originalNodes();

  result.hold = true; await open(); await held(); await close(); await result.release(); result.hold = false; await pause();
  await check("closing aborts and discards a late saved-field response", "!document.querySelector('.result-companion-dialog,[data-result-facts]')"); await originalNodes();
  result.hold = true; await open(); await held(); await column(1); await held(2);
  result.hold = false; await column(0); await ready(); await result.release(); await pause();
  await check("late field reads cannot replace a newer selected numeric field", `document.querySelector('[data-result-column]').value==='0'&&document.querySelector('[data-result-facts]').textContent.includes(${quote(RESULT_BROWSER_GOLD.maximum)})`); await close();
  result.failNext = 503; await open();
  await waitFor("document.querySelector('.result-companion [role=alert]')?.textContent.includes('could not read')", "result_transient_failure");
  const count = result.calls.length; await pause(); assert.equal(result.calls.length, count, "result_no_automatic_retry");
  await click("[data-result-retry]"); await ready(); await close();

  result.hold = true; await open(); await held();
  // Deliberate out-of-band callback of an existing saved-target control.
  await clickText(RESULT_CHAT_TITLES[1]);
  await waitFor(`!document.querySelector('.result-companion-dialog')&&document.querySelector('.breadcrumb strong')?.textContent===${quote(RESULT_CHAT_TITLES[1])}`, "result_target_changed");
  await result.release(); result.hold = false; await pause();
  await check("changing saved targets clears the earlier field check", "!document.querySelector('[data-result-facts]')");
  result.hold = true; await open(); await held(); result.historyRevision = "b".repeat(64); await result.release();
  await waitFor("!document.querySelector('.result-companion-dialog')", "result_history_changed");
  await check("history replacement cannot publish the held field check", "!document.querySelector('[data-result-facts]')");
  result.historyRevision = null; result.hold = false; await navigate("/"); await selectChat(0);
  result.hold = true; await open(); await held(); fixture.email = null; await navigate("/signin"); await signIn(emailB); await result.release(); result.hold = false; await pause();
  await check("owner replacement cannot restore another owner's held field check", "!document.querySelector('.result-companion-dialog,[data-result-facts]')");

  result.blockChunk = true; await navigate("/"); await selectChat(0);
  await fill(".opal-composer textarea", "Keep this draft if the optional result chunk fails");
  await evaluate("window.__resultComposer=document.querySelector('.opal-composer textarea');window.__resultTable=document.querySelector('.conversation table');true");
  await open(); await waitFor("document.querySelector('dialog[open] h2')?.textContent==='Result companion unavailable'", "result_optional_chunk_failure");
  await click("dialog[open] button"); await waitFor("!document.querySelector('dialog[open]')", "result_failed_chunk_closed"); await originalNodes();
  await check("optional chunk failure keeps the existing draft and table usable", "window.__resultComposer.value==='Keep this draft if the optional result chunk fails'&&!window.__resultComposer.disabled");
  result.blockChunk = false;
  assert.equal(fixture.queryCount(), queries, "result_journey_never_submits_analysis"); assert.equal(result.pending.length, 0);
  assert.ok(result.calls.length <= 80);
  return { kind: "mocked_saved_result_projection_not_actual_backend", fixture_sha256: RESULT_BROWSER_FIXTURE_SHA256,
    saved_rows: RESULT_BROWSER_GOLD.rows, brief_requests: result.calls.length, analytical_submissions: 0, pending_remaining: 0, peak_held: result.peakHeld,
    target_and_draft_changes: "out_of_band_existing_control_callbacks", optional_chunk_failure: "contained_close_preserves_workspace", geometry: result.geometry };
}
