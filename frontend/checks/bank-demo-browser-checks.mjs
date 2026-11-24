import assert from "node:assert/strict";
import { BANK_CHAT_TITLES, BANK_FIXTURE_SHA256, BANK_REPORT_ID, bankReportGold } from "./bank-demo-browser-fixture.mjs";

// Chrome's native button/summary activation needs the Enter character as well
// as keyDown; keyDown-only does not produce a native click. Keep the shared
// transport and every other journey's key semantics unchanged.
export const bankDemoKey = (dispatch, key) => dispatch(key, 0, key === "Enter" ? "\r" : undefined);
export async function bankDemoChooseFirst(dispatch) {
  // Closed native selects change with the arrows. Enter would open a popup,
  // causing the next Tab to dismiss it instead of reaching the Read button.
  await dispatch("Home"); await dispatch("ArrowDown");
}
export const bankDemoDoubledText = (normal, enlarged) => Number.isFinite(normal) && Number.isFinite(enlarged)
  && normal >= 14 && Math.abs(enlarged - normal * 2) <= 0.1;

// One opt-in, bounded mocked-API journey. All API/Chrome/profile/request limits
// and failure gates are supplied by the unchanged P05 production-build runner.
export async function runBankDemoChecks(ctx, { emailA, emailB, help, bank }) {
  const { fixture, check, click, clickText, fill, waitFor, evaluate, navigate, signIn, viewport, screenshot } = ctx;
  const key = value => bankDemoKey(ctx.key, value);
  const pause = () => new Promise(resolve => setTimeout(resolve, 80));
  const gold = bankReportGold(), quote = JSON.stringify;
  const open = async () => {
    const focused = await evaluate("(()=>{const trigger=document.querySelector('[data-open-companion]');trigger.focus();return document.activeElement===trigger})()");
    assert.equal(focused, true, "bank_tools_trigger_receives_keyboard_focus");
    await key("Enter");
    await waitFor("Boolean(document.querySelector('dialog[open] [data-bank-demo-open]'))", "bank_area_control");
    await click("[data-bank-demo-open]");
  };
  const close = async () => { await click("[data-close-companion]"); await waitFor("!document.querySelector('dialog[open]')", "bank_closed"); };
  const ready = () => waitFor("Boolean(document.querySelector('[data-bank-report-picker]'))", "bank_catalog_ready");
  const select = async () => {
    await evaluate("document.querySelector('[data-bank-report-picker]').focus();true");
    await bankDemoChooseFirst(key);
    await waitFor(`document.querySelector('[data-bank-report-picker]')?.value===${quote(BANK_REPORT_ID)}`, "bank_native_selection");
  };
  const read = async () => { await select(); await click("[data-bank-read]"); };
  const visibleReport = () => waitFor("Boolean(document.querySelector('[data-bank-report]'))", "bank_report_visible");
  const held = async () => {
    const end = performance.now() + 5500;
    while (bank.pending.length === 0 && performance.now() < end) await pause();
    assert.equal(bank.pending.length, 1, "bank_single_held_request");
  };
  const unchanged = () => check("fictional report tools preserve the existing composer and draft", "document.querySelector('.opal-composer textarea')===window.__bankComposer&&window.__bankComposer.value==='Synthetic bank journey unsent draft'");
  fixture.email = null; fixture.canQuery = true; help.enabled = false;
  await viewport(1440, 960); await navigate("/signin"); await signIn(emailA);
  await waitFor("document.querySelector('.opal-composer textarea')?.disabled===false", "bank_composer_ready");
  await fill(".opal-composer textarea", "Synthetic bank journey unsent draft");
  await evaluate("window.__bankComposer=document.querySelector('.opal-composer textarea');true");
  fixture.canQuery = false;
  await evaluate("(()=>{const c=new BroadcastChannel('aqua-session-events');c.postMessage({type:'changed'});c.close();return true})()");
  // Session revalidation keeps the previous workspace mounted, disabled and
  // inert. Only the visible workspace can accept the next keyboard action.
  await waitFor("document.querySelector('.opal-workspace:not([hidden]):not([inert]) .opal-composer textarea')?.disabled===true", "bank_no_analytical_grant");
  const queries = fixture.queryCount();

  bank.enabled = false; await open();
  await waitFor("document.querySelector('[data-bank-demo] [role=alert]')?.textContent.includes('not enabled')", "bank_default_off");
  await check("disabled bank demo is honest and separate from analytical access", "!document.querySelector('[data-bank-report-picker],[data-bank-report]')&&Boolean(document.querySelector('[data-bank-reload]'))");
  await close(); await unchanged();
  bank.enabled = true; bank.persona = "none"; await open();
  await waitFor("document.querySelector('[data-bank-demo]')?.textContent.includes('No fictional reports are assigned')", "bank_empty_scope");
  await check("empty host scope offers no report or client role selector", "!document.querySelector('[data-bank-report-picker],[data-bank-read],[data-bank-report]')&&document.querySelector('[data-bank-demo]').textContent.includes('not bank identity')");
  await close(); bank.persona = "teller"; await open(); await ready();
  await check("bank catalog works with help disabled and no analytical grant", "document.querySelector('.opal-composer textarea').disabled&&document.querySelector('[data-bank-read]').disabled&&document.querySelector('[data-bank-demo]').textContent.includes('No real bank is connected')");
  assert.equal(bank.calls.filter(item => item.method === "POST").length, 0, "bank_open_does_not_read_automatically");
  await select(); await key("Tab");
  await check("native report picker reaches explicit read by keyboard", "document.activeElement===document.querySelector('[data-bank-read]')");
  await key("Enter"); await visibleReport();
  await check("exact deposit aggregates retain every original string cell and trusted unit", `JSON.stringify([...document.querySelectorAll('[data-bank-report] tbody tr')].map(row=>[...row.cells].map(cell=>cell.textContent)))===${quote(JSON.stringify(gold.rows))}&&JSON.stringify([...document.querySelectorAll('[data-bank-report] th')].map(cell=>cell.textContent))===${quote(JSON.stringify(gold.columns.map(item => item.label + (item.unit === "text" ? "" : ` (${item.unit})`))))}`);
  await check("report labels expose fictional snapshot partial period scope and source", `(()=>{const panel=document.querySelector('[data-bank-demo]'),r=document.querySelector('[data-bank-report]');return panel.textContent.includes('teller — fictional scope')&&panel.textContent.includes('2026-11-16')&&r.textContent.includes('Fictional · Partial period')&&r.textContent.includes('2026-11-01')&&r.textContent.includes('not a complete month')&&panel.querySelector('[title=${quote(gold.sourceRevision)}]')!==null})()`);
  await evaluate("document.querySelector('[data-bank-report] .bank-demo__procedure summary').focus();true"); await key("Enter");
  await waitFor("document.querySelector('[data-bank-report] .bank-demo__procedure')?.open===true", "bank_procedure_keyboard_open");
  await check("canonical cited fictional procedure and all human next steps remain inert text", `(()=>{const p=document.querySelector('[data-bank-report] .bank-demo__procedure');return p.textContent.includes(${quote(gold.procedure.text)})&&p.textContent.includes(${quote(gold.procedure.sourceId)})&&p.textContent.includes(${quote(gold.procedure.version)})&&p.querySelector('[title=${quote(gold.procedure.contentSha256)}]')!==null&&JSON.stringify([...p.querySelectorAll('ol li')].map(el=>el.textContent))===${quote(JSON.stringify(gold.nextSteps.map(item => item.text)))}&&!p.querySelector('a,button,input')&&p.textContent.includes('No approval has been recorded')})()`);
  await screenshot("bank-demo-desktop-report");
  const normalCellFont = await evaluate("parseFloat(getComputedStyle(document.querySelector('.bank-demo__table td')).fontSize)");
  await viewport(320, 844, true);
  await evaluate("document.querySelector('.opal-workspace').style.setProperty('--pref-text-scale','2');document.querySelector('[data-bank-demo]').scrollIntoView();true");
  bank.geometry = await evaluate("(()=>{const d=document.querySelector('.companion-tools-dialog'),r=d.getBoundingClientRect(),t=d.querySelector('.bank-demo__table');const n=v=>Number.isFinite(v)?Math.round(v*100)/100:null;return {viewport:innerWidth,dialog:{left:n(r.left),right:n(r.right),client:d.clientWidth,scroll:d.scrollWidth},table:{client:t.clientWidth,scroll:t.scrollWidth,cell_font:n(parseFloat(getComputedStyle(t.querySelector('td')).fontSize))},controls:[...d.querySelectorAll('[data-bank-demo-open],[data-bank-report-picker],[data-bank-read],summary,[data-close-companion]')].slice(0,5).map(el=>({height:n(el.getBoundingClientRect().height),width:n(el.getBoundingClientRect().width)})),overflow:['.bank-demo-panel','.bank-demo__report','.bank-demo__table','.bank-demo__procedure','.bank-demo__picker','.bank-demo__facts'].map(selector=>{const el=d.querySelector(selector),b=el.getBoundingClientRect();return {kind:selector.slice(1),left:n(b.left),right:n(b.right),client:el.clientWidth,scroll:el.scrollWidth}})}})()");
  bank.geometry.normal_cell_font = normalCellFont;
  await check("320px doubled text keeps report and controls within the dialog with a local scrollable table", `(()=>{const d=document.querySelector('.companion-tools-dialog'),r=d.getBoundingClientRect(),t=d.querySelector('.bank-demo__table');return r.left>=-1&&r.right<=innerWidth+1&&d.scrollWidth<=d.clientWidth+1&&t.clientWidth>0&&t.scrollWidth>t.clientWidth&&[...d.querySelectorAll('[data-bank-demo-open],[data-bank-report-picker],[data-bank-read],summary,[data-close-companion]')].every(el=>el.getBoundingClientRect().height>=43.5)&&${bankDemoDoubledText(normalCellFont, bank.geometry.table.cell_font)}})()`);
  await screenshot("bank-demo-320-double-text");
  await evaluate("document.querySelector('.bank-demo__table').scrollIntoView({block:'start'});true");
  await screenshot("bank-demo-320-double-text-figures");
  await evaluate("document.querySelector('[data-close-companion]').scrollIntoView({block:'end'});true");
  await check("mobile doubled-text Close remains reachable by scrolling inside the dialog", "(()=>{const el=document.querySelector('[data-close-companion]'),r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight+1&&r.left>=0&&r.right<=innerWidth&&r.height>=44})()");
  await screenshot("bank-demo-320-double-text-close");
  await evaluate("document.querySelector('[data-close-companion]').focus();true"); await key("Tab");
  await check("real keyboard Tab remains within the bank dialog", "document.querySelector('.companion-tools-dialog').contains(document.activeElement)");
  await key("Escape"); await waitFor("!document.querySelector('dialog[open]')", "bank_escape_closed");
  await check("Escape returns keyboard focus to the tools opener", "document.activeElement===document.querySelector('[data-open-companion]')");
  await viewport(1440, 960); await evaluate("document.querySelector('.opal-workspace').style.setProperty('--pref-text-scale','1');true"); await unchanged();

  for (const [status, text] of [[403, "outside the current demo scope"], [503, "could not read"], [409, "source changed"]]) {
    await open(); await ready(); bank.failNext = status; await read();
    await waitFor(`document.querySelector('[data-bank-demo] [role=alert]')?.textContent.includes(${quote(text)})`, `bank_fixed_error_${status}`);
    const count = bank.calls.length; await pause();
    assert.equal(bank.calls.length, count, "bank_error_has_no_automatic_retry");
    await check(`HTTP ${status} clears report and requires explicit catalog reload`, "!document.querySelector('[data-bank-report],[data-bank-report-picker]')&&Boolean(document.querySelector('[data-bank-reload]'))");
    await click("[data-bank-reload]"); await ready(); await read(); await visibleReport(); await close();
  }
  await unchanged();
  await open(); await ready(); bank.wrongOwner = true; await read();
  await waitFor("Boolean(document.querySelector('[data-bank-demo] [role=alert]'))", "bank_cross_owner_denied");
  await check("a mismatched response owner never renders report data", "!document.querySelector('[data-bank-report]')");
  bank.wrongOwner = false; await close();

  bank.hold = "context"; await open(); await held();
  await check("held catalog exposes an accessible loading state without a picker", "Boolean(document.querySelector('[data-bank-demo] [role=status]'))&&!document.querySelector('[data-bank-report-picker]')");
  await close(); await bank.release(); bank.hold = null; await pause();
  await check("closing during catalog loading discards late data", "!document.querySelector('[data-bank-demo]')");
  await open(); await ready(); bank.hold = "report"; await read(); await held();
  await check("held read disables duplicate submission and shows reading status", "document.querySelector('[data-bank-read]').disabled&&document.querySelector('[data-bank-report-picker]').disabled&&document.querySelector('[data-bank-demo]').textContent.includes('Reading the selected fictional report')");
  await close(); await bank.release(); bank.hold = null; await pause(); await unchanged();
  await open(); await ready(); await check("reopening after a late closed read begins with an empty selection and no report", "document.querySelector('[data-bank-report-picker]').value===''&&!document.querySelector('[data-bank-report]')"); await close();

  await open(); await ready(); bank.hold = "report"; await read(); await held(); bank.historyRevision = "b".repeat(64); await bank.release();
  await waitFor("!document.querySelector('.companion-tools-dialog')", "bank_history_fence");
  await check("history invalidation clears the held private report", "!document.querySelector('[data-bank-report]')");
  bank.historyRevision = null; bank.hold = null; await navigate("/"); await waitFor("Boolean(document.querySelector('[data-open-companion]'))", "bank_reset_history");
  await open(); await ready(); bank.hold = "report"; await read(); await held();
  fixture.email = null; await navigate("/signin"); await signIn(emailB); await bank.release(); bank.hold = null; await pause();
  await check("owner switch cannot restore the previous owner’s held report", "!document.querySelector('.companion-tools-dialog,[data-bank-report]')&&!document.body.textContent.includes('1461250.00')");
  await open(); await ready(); bank.hold = "report"; await read(); await held();
  await evaluate("history.pushState({},'', '/settings');window.dispatchEvent(new PopStateEvent('popstate'));true");
  await waitFor("Boolean(document.querySelector('.settings-shell'))&&!document.querySelector('.companion-tools-dialog')", "bank_route_fence");
  await bank.release(); bank.hold = null; await pause();
  await check("settings navigation discards the report instead of rendering it under another route", "!document.querySelector('[data-bank-report]')");

  await navigate("/"); await waitFor(`document.querySelector('.desktop-sidebar')?.textContent.includes(${quote(BANK_CHAT_TITLES[0])})`, "bank_saved_targets_loaded");
  await clickText(BANK_CHAT_TITLES[0]);
  await waitFor(`document.querySelector('.breadcrumb strong')?.textContent===${quote(BANK_CHAT_TITLES[0])}`, "bank_first_target_selected");
  await open(); await ready(); bank.hold = "report"; await read(); await held();
  // A deliberate out-of-band existing-control callback models an asynchronous
  // target change while the native modal is open; it is not a pointer/keyboard
  // action through the modal's inert background.
  await clickText(BANK_CHAT_TITLES[1]);
  await waitFor(`!document.querySelector('.companion-tools-dialog')&&document.querySelector('.breadcrumb strong')?.textContent===${quote(BANK_CHAT_TITLES[1])}`, "bank_target_fence");
  await bank.release(); bank.hold = null; await pause();
  await check("out-of-band saved target change discards the earlier held report", "!document.querySelector('[data-bank-report]')&&!document.body.textContent.includes('1461250.00')");
  assert.equal(fixture.queryCount(), queries, "bank_journey_never_submitted_sql_or_analysis");
  assert.equal(bank.pending.length, 0); assert.equal(bank.peakHeld, 1); assert.ok(bank.calls.length <= 80);
  return { kind: "mocked_original_fictional_http_projection", fixture_sha256: BANK_FIXTURE_SHA256,
    bank_requests: bank.calls.length, analytical_submissions: 0, held_remaining: bank.pending.length, peak_held: bank.peakHeld,
    source_report_id: BANK_REPORT_ID, actual_backend_tested: false, target_change: "out_of_band_existing_control_callback" };
}
