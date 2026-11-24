// Real FastAPI/TestClient and disposable app PostgreSQL via the existing JSONL
// bridge. Expected figures alone are loaded from the original fictional packet;
// this module never installs the mocked HTTP fixture.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

const packet = readFileSync(new URL("./bank-demo-browser-data.json", import.meta.url));
assert.ok(packet.length < 20000);
assert.equal(createHash("sha256").update(packet).digest("hex"), "47bb678ace09af350d576ea218927edc26dc15cebbcd160e31d53bd93894da47");
const original = JSON.parse(packet), reportId = "deposit_portfolio_summary";
const gold = original.reports.find(item => item.result.reportId === reportId).result;
const quote = JSON.stringify;

export function bankRealMode(journey, analysis) {
  if (journey !== null && journey !== "bank-demo" || typeof analysis !== "boolean" || journey === "bank-demo" && analysis) throw Error("real_bank_fixture_mode_invalid");
  return journey === "bank-demo";
}
export function bankRealCleanupConfirmed(value) {
  return value?.closed === true && value.failed === false && value.abandoned === 0 && value.remaining === 0 && value.armed === false
    && Number.isSafeInteger(value.captured) && value.captured >= 0 && value.captured <= 4 && value.captured === value.released;
}

export async function bankRealKey(send, key) {
  const codes = { Enter: 13, Tab: 9, Escape: 27, Home: 36, ArrowDown: 40 };
  if (!Object.hasOwn(codes, key)) throw Error("real_bank_key_invalid");
  for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", { type, key, code: key, windowsVirtualKeyCode: codes[key], modifiers: 0, ...(key === "Enter" ? { text: "\r" } : {}) });
}

// Only an already-computed real report can be delayed. No worker blocking,
// request mutation, fake API result, retry or unbounded queue is introduced.
export class BankDemoResponseGate {
  #now; #setTimer; #clearTimer; #timer = null; #slot = null; #armed = false; #closed = false;
  #failure = null; #captured = 0; #released = 0; #abandoned = 0;
  constructor({ now = () => performance.now(), setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
    if ([now, setTimer, clearTimer].some(value => typeof value !== "function")) throw Error("real_bank_gate_clock_invalid");
    this.#now = now; this.#setTimer = setTimer; this.#clearTimer = clearTimer;
  }
  assertHealthy() { if (this.#failure) throw Error(this.#failure); if (this.#closed) throw Error("real_bank_gate_closed"); }
  arm() {
    this.assertHealthy();
    if (this.#armed || this.#slot || this.#captured >= 4) throw Error("real_bank_hold_capacity");
    this.#armed = true;
  }
  capture(request, response, finish) {
    this.assertHealthy();
    if (!this.#armed) return false;
    const field = (object, key) => {
      try {
        if (!object || typeof object !== "object" || Array.isArray(object)) throw Error();
        const descriptor = Object.getOwnPropertyDescriptor(object, key);
        if (!descriptor || !Object.hasOwn(descriptor, "value")) throw Error();
        return descriptor.value;
      } catch { throw Error("real_bank_hold_response_invalid"); }
    };
    if (field(request, "method") !== "POST") return false;
    let url;
    try { const value = field(request, "url"); if (typeof value !== "string") throw Error(); url = new URL(value); } catch { throw Error("real_bank_hold_request_invalid"); }
    if (url.pathname !== "/api/v1/bank-demo/reports") return false;
    const encoded = field(response, "bodyBase64");
    if (!/^http:\/\/127\.0\.0\.1:[1-9][0-9]{3,4}$/.test(url.origin) || url.port < 1024 || url.port > 65535 || url.search || url.hash || url.username || url.password
      || field(response, "status") !== 200 || typeof finish !== "function" || typeof encoded !== "string" || encoded.length > 21848
      || !/^[A-Za-z0-9+/]*={0,2}$/.test(encoded) || Buffer.from(encoded, "base64").length > 16384
      || Buffer.from(encoded, "base64").toString("base64") !== encoded) throw Error("real_bank_hold_response_invalid");
    if (this.#slot) throw Error("real_bank_hold_capacity");
    const started = this.#now();
    if (typeof started !== "number" || !Number.isFinite(started) || started < 0) throw Error("real_bank_gate_clock_invalid");
    const until = started + 4000;
    this.#armed = false; this.#captured++;
    this.#slot = { finish, started, until };
    this.#timer = this.#setTimer(() => {
      this.#failure = "real_bank_held_response_deadline"; this.#slot = null; this.#timer = null; this.#abandoned++;
    }, 4000);
    return true;
  }
  async release() {
    this.assertHealthy(); const slot = this.#slot;
    if (!slot) throw Error("real_bank_hold_missing");
    const now = this.#now();
    if (typeof now !== "number" || !Number.isFinite(now) || now < slot.started || now >= slot.until) {
      this.#clearTimer(this.#timer); this.#timer = null; this.#slot = null; this.#abandoned++;
      this.#failure = "real_bank_held_response_deadline"; throw Error(this.#failure);
    }
    this.#clearTimer(this.#timer); this.#timer = null; this.#slot = null; this.#released++;
    await slot.finish();
  }
  snapshot() { return { captured: this.#captured, released: this.#released, remaining: this.#slot ? 1 : 0, armed: this.#armed, abandoned: this.#abandoned, failed: this.#failure !== null, closed: this.#closed }; }
  close() {
    if (this.#timer !== null) this.#clearTimer(this.#timer);
    if (this.#slot || this.#armed) { this.#abandoned++; this.#failure ||= "real_bank_hold_abandoned"; }
    this.#timer = null; this.#slot = null; this.#armed = false; this.#closed = true;
  }
}

export async function runRealBankDemoChecks(ctx) {
  const { check, click, evaluate, waitFor, rawRequest, screenshot, session, gate, send, analyticalCount, companionReads, logout } = ctx;
  const key = value => bankRealKey(send, value);
  const open = async () => {
    await click("[data-open-companion]");
    await waitFor("Boolean(document.querySelector('dialog[open] [data-bank-demo-open]'))", "real_bank_area");
    await click("[data-bank-demo-open]");
    await waitFor("Boolean(document.querySelector('[data-bank-report-picker]'))", "real_bank_catalog");
  };
  const select = async () => {
    await evaluate("document.querySelector('[data-bank-report-picker]').focus();true");
    await key("Home"); await key("ArrowDown");
    await waitFor(`document.querySelector('[data-bank-report-picker]')?.value===${quote(reportId)}`, "real_bank_selected");
  };
  const read = async () => { await select(); await key("Tab"); await check("real bank keyboard selection reaches explicit Read", "document.activeElement===document.querySelector('[data-bank-read]')"); await key("Enter"); };
  const held = async () => {
    const end = performance.now() + 4000;
    while (gate.snapshot().remaining !== 1 && performance.now() < end) { gate.assertHealthy(); await new Promise(resolve => setTimeout(resolve, 20)); }
    assert.equal(gate.snapshot().remaining, 1, "real_bank_response_held");
  };
  const baseline = analyticalCount(); assert.equal(baseline, 0, "real_bank_setup_has_no_analysis_submissions");
  await evaluate("window.__realBankComposer=document.querySelector('.opal-composer textarea');window.__realBankDraft=window.__realBankComposer.value;true");
  const menuResponse = await rawRequest("GET", "/api/v1/bank-demo/context"); assert.equal(menuResponse.status, 200);
  const menu = JSON.parse(menuResponse.body);
  assert.equal(menu.owner_id, session.user.id); assert.equal(session.can_query, false);
  assert.deepEqual(menu.reports, original.contexts.teller.reports);
  assert.equal(menu.context.persona, "teller"); assert.equal(menu.context.sourceRevision, gold.sourceRevision);
  await open();
  await check("real no-dataset account receives only the fixed teller catalog", "document.querySelector('.opal-composer textarea').disabled&&document.querySelector('[data-bank-report-picker]').options.length===3&&document.querySelector('[data-bank-demo]').textContent.includes('teller — fictional scope')");
  await click("[data-bank-calculator] > summary");
  await evaluate("(()=>{const select=document.querySelector('[data-calc-operation]');select.value='simple_interest';select.dispatchEvent(new Event('change',{bubbles:true}));return true;})()");
  for (const [field, value] of Object.entries({ principal_usd: "1200", annual_rate_percent: "3", term_months: "2" })) {
    await evaluate("(()=>{const el=document.querySelector('[data-calc-input=" + field + "]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el," + quote(value) + ");el.dispatchEvent(new Event('input',{bubbles:true}));return true;})()");
  }
  await click("[data-calc-review]");
  await waitFor("Boolean(document.querySelector('[data-calc-confirm]'))","real_bank_employee_review");
  await check("review holds calculation before employee confirmation","!document.querySelector('.bank-calculator__result')");
  await click("[data-calc-confirm]");
  await waitFor("document.querySelector('.bank-calculator__result')?.textContent.includes('6.00 USD')","real_bank_confirmed_illustration");
  await read(); await waitFor("Boolean(document.querySelector('[data-bank-report]'))", "real_bank_report_visible");
  await check("reading a new source clears old confirmed amounts","!document.querySelector('.bank-calculator__result')&&document.querySelector('[data-calc-operation]').value===''");
  await check("real report preserves all original deposit cell strings", `JSON.stringify([...document.querySelectorAll('[data-bank-report] tbody tr')].map(row=>[...row.cells].map(cell=>cell.textContent)))===${quote(JSON.stringify(gold.rows))}`);
  const setEvidence = async mode => {
    await evaluate(`(()=>{const el=document.querySelector('[data-bank-evidence]');el.value=${quote(mode)};el.dispatchEvent(new Event("change",{bubbles:true}));return true;})()`);
    await waitFor("!document.querySelector('[data-bank-report]')", "real_bank_new_requirements_clear_old_figures");
  };
  const setDay = (index, day) => evaluate(`(()=>{const el=document.querySelectorAll('.bank-demo__dates input')[${index}];Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,${quote(day)});el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return true;})()`);
  await setEvidence("institution");
  await click("[data-bank-read]");
  await waitFor("document.querySelector('[data-bank-demo] [role=status]')?.textContent.includes('approved record')", "real_bank_official_source_unavailable");
  await check("institutional request withholds every synthetic figure", "!document.querySelector('[data-bank-report]')");
  await setEvidence("dates");
  await setDay(0, gold.periodStart); await setDay(1, "2026-11-30"); await click("[data-bank-read]");
  await waitFor("document.querySelector('[data-bank-demo] [role=status]')?.textContent.includes('requested period is unavailable')", "real_bank_full_month_unavailable");
  await check("a partial month never fills a complete-month request", "!document.querySelector('[data-bank-report]')");
  await setDay(1, gold.periodEnd); await click("[data-bank-read]");
  await waitFor("Boolean(document.querySelector('[data-bank-report]'))", "real_bank_exact_period_visible");
  await check("an exact date correction restores the original authorized rows", `JSON.stringify([...document.querySelectorAll('[data-bank-report] tbody tr')].map(row=>[...row.cells].map(cell=>cell.textContent)))===${quote(JSON.stringify(gold.rows))}`);
  await check("real report exposes trusted units source snapshot and partial period", `(()=>{const p=document.querySelector('[data-bank-demo]');return p.textContent.includes('2026-11-16')&&p.textContent.includes('Fictional · Partial period')&&p.querySelector('[title=${quote(gold.sourceRevision)}]')!==null&&JSON.stringify([...p.querySelectorAll('th')].map(cell=>cell.textContent))===${quote(JSON.stringify(gold.columns.map(column => column.label + (column.unit === "text" ? "" : ` (${column.unit})`))))}})()`);
  await evaluate("document.querySelector('.bank-demo__procedure summary').focus();true"); await key("Enter");
  await waitFor("document.querySelector('.bank-demo__procedure')?.open===true", "real_bank_procedure");
  await check("real cited fictional procedure and human suggestions are source-bound inert text", `(()=>{const p=document.querySelector('.bank-demo__procedure');return p.textContent.includes(${quote(gold.procedure.text)})&&p.textContent.includes(${quote(gold.procedure.sourceId)})&&p.textContent.includes(${quote(gold.procedure.version)})&&p.querySelector('[title=${quote(gold.procedure.contentSha256)}]')!==null&&JSON.stringify([...p.querySelectorAll('ol li')].map(el=>el.textContent))===${quote(JSON.stringify(gold.nextSteps.map(item => item.text)))}&&!p.querySelector('button,a,input')&&p.textContent.includes('No approval has been recorded')})()`);
  await check("real report reading keeps the same unsent composer", "document.querySelector('.opal-composer textarea')===window.__realBankComposer&&window.__realBankComposer.value===window.__realBankDraft");
  await screenshot("real-bank-deposit-report"); await key("Escape");
  await waitFor("!document.querySelector('dialog[open]')", "real_bank_closed");

  const headers = { "X-CSRF-Token": session.csrf_token }, body = { schemaVersion: 1, report_id: reportId, expected_source_revision: menu.context.sourceRevision };
  assert.equal((await rawRequest("POST", "/api/v1/bank-demo/reports", body)).status, 403, "real_bank_missing_csrf_denied");
  assert.equal((await rawRequest("POST", "/api/v1/bank-demo/reports", { ...body, report_id: "reconciliation_summary" }, headers)).status, 403, "real_bank_outside_teller_denied");
  assert.equal((await rawRequest("POST", "/api/v1/bank-demo/reports", { ...body, expected_source_revision: "0".repeat(64) }, headers)).status, 409, "real_bank_stale_source_denied");
  assert.equal((await rawRequest("POST", "/api/v1/bank-demo/reports", { ...body, persona: "manager" }, headers)).status, 422, "real_bank_client_authority_denied");
  await check("real bank API denies missing CSRF cross-scope stale source and role injection", "!document.querySelector('[data-bank-report]')");

  await open(); gate.arm(); await read(); await held(); await key("Escape");
  await waitFor("!document.querySelector('dialog[open]')", "real_bank_held_close"); await gate.release();
  await open(); await check("late real completion after close cannot reappear in a fresh dialog", "!document.querySelector('[data-bank-report]')&&document.querySelector('[data-bank-report-picker]').value===''");
  gate.arm(); await read(); await held();
  // Model another tab replacing the session using actual cookie/auth APIs.
  // The existing fixed Google verifier is synthetic; cookie/session code is real.
  assert.equal((await rawRequest("POST", "/api/auth/logout", {}, headers)).status, 204, "real_bank_old_session_logged_out");
  const configResponse = await rawRequest("GET", "/api/auth/config"); assert.equal(configResponse.status, 200);
  const config = JSON.parse(configResponse.body);
  assert.equal((await rawRequest("POST", "/api/auth/google", { credential: JSON.stringify({ nonce: config.nonce }) }, { "X-CSRF-Token": config.csrf_token })).status, 200, "real_bank_second_owner_cookie");
  const nextResponse = await rawRequest("GET", "/api/auth/me"); assert.equal(nextResponse.status, 200);
  const nextSession = JSON.parse(nextResponse.body); assert.notEqual(nextSession.user.id, session.user.id); assert.equal(nextSession.can_query, false);
  await evaluate("(()=>{const c=new BroadcastChannel('aqua-session-events');c.postMessage({type:'changed'});c.close();return true})()");
  await waitFor("!document.querySelector('.companion-tools-dialog')&&Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "real_bank_owner_replacement_teardown");
  await gate.release(); await open();
  await check("new actual cookie owner cannot display the previous owner’s delayed report", "!document.querySelector('[data-bank-report]')&&document.querySelector('[data-bank-report-picker]').value===''");
  const nextMenu = await rawRequest("GET", "/api/v1/bank-demo/context"); assert.equal(nextMenu.status, 200); assert.equal(JSON.parse(nextMenu.body).owner_id, nextSession.user.id);
  await key("Escape"); gate.assertHealthy();
  assert.deepEqual(gate.snapshot(), { captured: 2, released: 2, remaining: 0, armed: false, abandoned: 0, failed: false, closed: false });
  assert.equal(analyticalCount(), 0, "real_bank_never_submitted_analytical_query");
  const helpStatuses = companionReads(); assert.ok(helpStatuses.length > 0 && helpStatuses.every(status => status === 404), "real_bank_works_with_actual_help_default_off");
  await logout(); assert.equal((await rawRequest("GET", "/api/auth/me")).status, 401, "real_bank_second_owner_session_revoked");
  return { transport: "real_fastapi_testclient_disposable_postgres_jsonl", persona: "fixed_teller", report_id: reportId,
    actual_registration_session_admission_sql: true, analytical_submissions: 0, model_calls: 0, provider_calls: 0,
    response_hold: gate.snapshot(), owner_boundary: "actual_cookie_replacement_and_modeled_cross_tab_signal", real_bank_connected: false };
}
