import assert from "node:assert/strict";
import { ensureNavigation } from "./homepage-browser-actions.mjs";
import { NOTE_IDS, NOTE_CHAT_TITLES, NOTES_GOLD, NOTES_FIXTURE_SHA256 } from "./p05-context-notes-fixture.mjs";

export const notesKey = (dispatch, key) => dispatch(key, 0, key === "Enter" ? "\r" : undefined);
export const notesTextDoubled = (before, after) => Number.isFinite(before) && Number.isFinite(after) && before >= 14 && Math.abs(after - before * 2) <= 0.1;


export function notesEvidence(notes, analysisCalls) {
  assert.equal(analysisCalls, 0, "notes_entire_journey_zero_analysis");
  assert.equal(notes.pending.length, 0, "notes_no_unreleased_replies");
  assert.ok(notes.calls.length <= 80, "notes_request_cap");
  assert.ok(Number.isInteger(notes.peakHeld) && notes.peakHeld >= 0 && notes.peakHeld <= 4, "notes_hold_cap");
  assert.ok(Number.isInteger(notes.chunkDenials) && notes.chunkDenials > 0, "notes_fresh_document_chunk_denied");
  return { kind: "context_notes_mocked_api_only", fixture_sha256: NOTES_FIXTURE_SHA256, notes_requests: notes.calls.length,
    mutations: notes.calls.filter(call => ["create", "save", "forget"].includes(call.action)).length, analysis_calls: 0, model_calls: 0,
    peak_held: notes.peakHeld, chunk_denials: notes.chunkDenials, out_of_band_callbacks: ["composer", "target", "history", "owner"], physical_keyboard: true, geometry: notes.geometry };
}

// These intercepted APIs prove UI behavior only. Out-of-band authority callbacks
// below are labeled separately from real Input.dispatchKeyEvent navigation.
export async function runContextNotesChecks(ctx, { emailA, emailB, notes }) {
  const { fixture, check, click, clickText, fill, waitFor, evaluate, navigate, signIn, viewport, screenshot } = ctx;
  const quote = JSON.stringify, key = value => notesKey(ctx.key, value), pause = () => new Promise(resolve => setTimeout(resolve, 80));
  const calls = action => notes.calls.filter(call => call.action === action).length;
  const selected = id => `[data-notes-select="${id}"]`;
  const selectChat = async index => {
    await ensureNavigation(ctx);
    await waitFor(`Boolean([...document.querySelectorAll('button')].find(el=>el.textContent.trim()===${quote(NOTE_CHAT_TITLES[index])}))`, "notes_saved_chat_ready");
    await clickText(NOTE_CHAT_TITLES[index]);
    await waitFor(`document.querySelector('.breadcrumb strong')?.textContent===${quote(NOTE_CHAT_TITLES[index])}&&Boolean(document.querySelector('.conversation table'))`, "notes_saved_chat_loaded");
  };
  const library = () => waitFor("Boolean(document.querySelector('[data-notes-new]'))", "notes_library_ready");
  const open = async () => { await click("[data-open-companion]"); await waitFor("Boolean(document.querySelector('dialog[open]'))", "notes_dialog_open");
    await waitFor("Boolean(document.querySelector('[data-notes-open]'))", "notes_area_available"); await click("[data-notes-open]"); };
  const close = async () => { await click("[data-close-companion]"); await waitFor("!document.querySelector('dialog[open]')", "notes_dialog_closed"); };
  const read = async (id = NOTE_IDS.first) => { await click(selected(id)); await waitFor("Boolean(document.querySelector('[data-notes-body]'))", "notes_body_read"); };
  const prepare = async () => { await click("[data-notes-prepare]"); await waitFor("Boolean(document.querySelector('[data-notes-preview]'))", "notes_prepared_for_review"); };
  const held = async () => { const end = performance.now() + 5500; while (notes.pending.length !== 1 && performance.now() < end) await pause(); assert.equal(notes.pending.length, 1, "notes_one_bounded_reply_held"); };
  const retainNodes = () => check("saved-note tools retain the existing composer and table nodes", "document.querySelector('.opal-composer textarea')===window.__notesComposer&&document.querySelector('.conversation table')===window.__notesTable");
  const captureNodes = () => evaluate("window.__notesComposer=document.querySelector('.opal-composer textarea');window.__notesTable=document.querySelector('.conversation table');true");
  fixture.email = null; fixture.canQuery = true; await viewport(1440, 960); await navigate("/signin"); await signIn(emailA); await selectChat(0);
  const queries = fixture.queryCount(); assert.equal(queries, 0);
  await fill(".opal-composer textarea", "Existing notes demonstration draft"); await captureNodes();

  notes.enabled = false; await open();
  await waitFor("document.querySelector('.context-notes [role=alert]')?.textContent.includes('not enabled')", "notes_default_off_state");
  await close(); await retainNodes(); notes.enabled = true;
  await open(); await library(); assert.equal(calls("read"), 0, "notes_list_does_not_read_bodies");
  await check("saved library is metadata-only and unavailable context remains generic", "(()=>{const s=document.querySelector('.context-notes');return s.textContent.includes('Unavailable saved context')&&s.textContent.includes('unverified')&&!s.querySelector('[data-notes-body]')&&!s.querySelector('[data-notes-preview]')&&window.__notesComposer.value==='Existing notes demonstration draft'})()");
  await read();
  await check("explicit selection shows exact original saved text and unverified definition", `document.querySelector('[data-notes-body]').value===${quote(NOTES_GOLD.body)}&&document.querySelector('[data-notes-label]').value===${quote(NOTES_GOLD.label)}&&document.querySelector('[data-notes-kind]').value==='metric_definition'`);
  await prepare();
  await check("fresh preparation is an editable exact-text preview without changing the composer", `document.querySelector('[data-notes-draft]').value===${quote(NOTES_GOLD.body)}&&document.querySelector('[data-notes-preview]').textContent.includes('configured model or provider')&&window.__notesComposer.value==='Existing notes demonstration draft'`);
  await fill("[data-notes-draft]", NOTES_GOLD.applied); await click("[data-notes-apply]");
  await waitFor("!document.querySelector('dialog[open]')", "notes_explicit_apply_closed");
  await check("explicit Apply updates only the same composer; normal Send stays separate", `document.querySelector('.opal-composer textarea')===window.__notesComposer&&window.__notesComposer.value===${quote(NOTES_GOLD.applied)}`);
  assert.equal(fixture.queryCount(), queries, "notes_prepare_apply_zero_analysis"); await retainNodes();

  await open(); await library(); await click("[data-notes-new]");
  await fill("[data-notes-label]", NOTES_GOLD.newLabel); await fill("[data-notes-body]", NOTES_GOLD.counterText);
  await check("saved text counters independently measure UTF16 units and UTF8 bytes", "document.querySelector('[id$=-body-help]').textContent.startsWith('4/2000 text units · 7/2048 bytes.')");
  await fill("[data-notes-body]", NOTES_GOLD.newBody);
  const creations = calls("create"); await click("[data-notes-save]");
  await waitFor("document.querySelector('.context-notes [role=status]')?.textContent.includes('Saved your note')", "notes_explicit_create");
  assert.equal(calls("create"), creations + 1, "notes_one_explicit_create");
  await fill("[data-notes-body]", NOTES_GOLD.correction);
  await check("unsaved correction disables preparation and clears prior previews", "document.querySelector('[data-notes-prepare]').disabled&&!document.querySelector('[data-notes-preview]')");
  const saves = calls("save"); await click("[data-notes-save]");
  await waitFor("document.querySelector('.context-notes [role=status]')?.textContent.includes('Saved your correction')", "notes_correction_saved");
  assert.equal(calls("save"), saves + 1, "notes_one_explicit_CAS_correction"); await prepare();
  await check("correction prepares one advanced revision with exact corrected bytes", `document.querySelector('[data-notes-draft]').value===${quote(NOTES_GOLD.correction)}&&document.querySelector('[data-notes-preview]').textContent.includes('revision 2')`);
  await read(NOTE_IDS.second);
  await check("changing selected notes discards the previous body and preparation", `document.querySelector('[data-notes-body]').value===${quote(NOTES_GOLD.second)}&&!document.querySelector('[data-notes-preview]')`);
  const reads = calls("read"); await click(selected(NOTE_IDS.unavailable));
  await check("unavailable selection has no old body or label and no automatic read", "!document.querySelector('[data-notes-body],[data-notes-preview]')&&document.querySelector('.context-notes').textContent.includes('earlier label and text are not shown')");
  assert.equal(calls("read"), reads); await click("[data-notes-forget]");
  await check("forget requires separate confirmation and explains retained chat copies", "Boolean(document.querySelector('[data-notes-forget-confirm]'))&&document.querySelector('.context-notes').textContent.includes('Copies you already sent remain in chat history')");
  await click("[data-notes-forget-confirm]");
  await waitFor(`!document.querySelector(${quote(selected(NOTE_IDS.unavailable))})`, "notes_unavailable_forgotten");
  await check("confirmed forget removes only the library entry and keeps the current composer", `window.__notesComposer.value===${quote(NOTES_GOLD.applied)}&&document.querySelector('.context-notes').textContent.includes('Copies already sent in chat history are unchanged')`);

  await read(); notes.failNext = 409; await click("[data-notes-prepare]");
  await waitFor("document.querySelector('.context-notes [role=alert]')?.textContent.includes('context or access changed')", "notes_revision_conflict");
  await check("409 discards held content and requires explicit reload without replacing composer", `!document.querySelector('[data-notes-body],[data-notes-new],[data-notes-preview]')&&window.__notesComposer.value===${quote(NOTES_GOLD.applied)}`);
  await click("[data-notes-reload]"); await library(); await read();
  notes.failAfterWrite = true; await fill("[data-notes-body]", "A correction accepted before a simulated lost acknowledgement.");
  const uncertainSaves = calls("save"); await click("[data-notes-save]");
  await waitFor("document.querySelector('.context-notes [role=alert]')?.textContent.includes('could not confirm this change')", "notes_unconfirmed_write");
  await pause(); assert.equal(calls("save"), uncertainSaves + 1, "notes_uncertain_write_never_replayed");
  await check("unconfirmed write clears text and blocks further mutations until reload", "!document.querySelector('[data-notes-body],[data-notes-save],[data-notes-new]')&&Boolean(document.querySelector('[data-notes-reload]'))");
  await click("[data-notes-reload]"); await library();
  await check("explicit reconciliation reads only metadata before a new selection", "!document.querySelector('[data-notes-body],[data-notes-preview]')");
  await read(); await check("fresh selection reconciles a confirmed saved snapshot without resending the write", "document.querySelector('[data-notes-body]').value==='A correction accepted before a simulated lost acknowledgement.'");
  await prepare();
  // Existing controlled-input callbacks simulate a concurrent background edit;
  // they are not physical actions through the modal's inert background.
  await fill(".opal-composer textarea", "Newer draft must survive notes"); await click("[data-notes-apply]");
  await waitFor("document.querySelector('.context-notes [role=alert]')?.textContent.includes('composer changed')", "notes_draft_conflict");
  await close(); await check("a changed target draft survives attempted note application", "window.__notesComposer.value==='Newer draft must survive notes'");

  await open(); await library(); await read(); await prepare();
  const normal = await evaluate("({text:parseFloat(getComputedStyle(document.querySelector('.context-notes > p')).fontSize),select:parseFloat(getComputedStyle(document.querySelector('[data-notes-kind]')).fontSize)})");
  await viewport(320, 844, true); await evaluate("document.querySelector('.opal-workspace').style.setProperty('--pref-text-scale','2');true");
  notes.geometry = await evaluate("(()=>{const d=document.querySelector('.companion-tools-dialog'),r=d.getBoundingClientRect();return {width:innerWidth,left:r.left,right:r.right,client:d.clientWidth,scroll:d.scrollWidth,text:parseFloat(getComputedStyle(d.querySelector('.context-notes > p')).fontSize),select:parseFloat(getComputedStyle(d.querySelector('[data-notes-kind]')).fontSize),controlCount:d.querySelectorAll('button:not(:disabled),input,select,textarea').length}})()");
  assert.equal(notesTextDoubled(normal.text, notes.geometry.text), true, "notes_actual_text_doubled");
  assert.equal(notesTextDoubled(normal.select, notes.geometry.select), true, "notes_actual_select_text_doubled");
  await check("320px doubled text keeps labeled 44px controls inside the notes dialog", "(()=>{const d=document.querySelector('.companion-tools-dialog'),r=d.getBoundingClientRect();return r.left>=-1&&r.right<=innerWidth+1&&d.scrollWidth<=d.clientWidth+1&&[...d.querySelectorAll('button:not(:disabled),input,select,textarea')].every(el=>el.getBoundingClientRect().height>=43.5)&&[...d.querySelectorAll('input,select,textarea')].every(el=>el.labels.length===1)})()");
  await screenshot("context-notes-320-double-text");
  await evaluate("document.querySelector('[data-close-companion]').focus();true"); await key("Tab");
  await check("native Tab wraps from Close to the first area button", "document.activeElement===document.querySelector('.companion-tools__choice button')");
  let reachable = false; const nativeTags = new Set();
  for (let i = 0; i < 40; i++) {
    nativeTags.add(await evaluate("document.activeElement.tagName"));
    if (await evaluate("document.activeElement===document.querySelector('[data-close-companion]')")) { reachable = true; break; }
    await key("Tab");
  }
  assert.equal(reachable, true, "notes_close_reachable_by_physical_keyboard");
  for (const tag of ["INPUT", "SELECT", "TEXTAREA"]) assert.ok(nativeTags.has(tag), `notes_native_Tab_reached_${tag.toLowerCase()}`); await screenshot("context-notes-keyboard-close"); await key("Escape");
  await waitFor("!document.querySelector('dialog[open]')", "notes_escape_closed"); await viewport(1440,960);
  await evaluate("document.querySelector('.opal-workspace').style.setProperty('--pref-text-scale','1');true"); await retainNodes();

  notes.hold = "read"; await open(); await library(); await click(selected(NOTE_IDS.first)); await held(); await close(); await notes.release(); notes.hold = null; await pause();
  await check("closing discards a late selected-note body", "!document.querySelector('.context-notes,[data-notes-body],[data-notes-preview]')"); await retainNodes();
  notes.hold = "read"; await open(); await library(); await click(selected(NOTE_IDS.first)); await held();
  // Deliberate out-of-band callback of the existing saved-target control.
  await clickText(NOTE_CHAT_TITLES[1]);
  await waitFor(`!document.querySelector('.context-notes')&&document.querySelector('.breadcrumb strong')?.textContent===${quote(NOTE_CHAT_TITLES[1])}`, "notes_target_replaced");
  await notes.release(); notes.hold = null; await pause(); await check("target replacement cannot publish the earlier note body", "!document.querySelector('[data-notes-body],[data-notes-preview]')");
  notes.hold = "read"; await open(); await library(); await click(selected(NOTE_IDS.first)); await held();
  notes.responseHistoryRevision = "b".repeat(64); await notes.release();
  await waitFor("!document.querySelector('.context-notes')", "notes_history_replaced");
  await check("history replacement discards held note text instead of adopting a new scope", "!document.querySelector('[data-notes-body],[data-notes-preview]')");
  notes.responseHistoryRevision = null; notes.hold = null; await navigate("/"); await selectChat(0);
  await open(); await library(); await read(); fixture.canQuery = false;
  const preparesBeforeRevocation = notes.calls.filter(call => call.action === "prepare").length;
  await click("[data-notes-prepare]");
  // The grant transition changes the opaque scope. The real service checks
  // expected_scope_id before access, so this stale request is exactly a 409.
  await waitFor("document.querySelector('.context-notes [role=alert]')?.textContent==='Saved context or access changed. Reload the library before continuing. Your composer was kept.'", "notes_fresh_scope_denied");
  await pause(); assert.equal(notes.calls.filter(call => call.action === "prepare").length, preparesBeforeRevocation + 1, "notes_scope_denial_is_not_retried");
  await check("fresh grant scope denial clears displayed note text and requires Reload", "!document.querySelector('[data-notes-body],[data-notes-preview],[data-notes-prepare]')&&document.querySelector('.context-notes button')?.textContent==='Check saved notes availability'"); await close(); fixture.canQuery = true;
  notes.hold = "read"; await open(); await library(); await click(selected(NOTE_IDS.first)); await held();
  fixture.email = null; await navigate("/signin"); await signIn(emailB); await notes.release(); notes.hold = null; await pause();
  await check("owner replacement cannot restore another owner's held body", "!document.querySelector('.context-notes,[data-notes-body],[data-notes-preview]')");

  // navigate() passes about:blank, guaranteeing a new document and React.lazy cache.
  notes.blockChunk = true; await navigate("/"); await selectChat(0);
  await fill(".opal-composer textarea", "Keep this draft when the optional tools chunk fails"); await captureNodes();
  await click("[data-open-companion]"); await waitFor("document.querySelector('dialog[open] h2')?.textContent==='Aqua tools unavailable'", "notes_fresh_document_chunk_failure");
  assert.ok(notes.chunkDenials > 0, "notes_actual_fresh_document_chunk_denial");
  await click("dialog[open] button"); await waitFor("!document.querySelector('dialog[open]')", "notes_failed_chunk_closed"); await retainNodes();
  await check("fresh-document optional failure preserves the saved table and editable draft", "window.__notesComposer.value==='Keep this draft when the optional tools chunk fails'&&!window.__notesComposer.disabled");
  notes.blockChunk = false;
  return notesEvidence(notes, fixture.queryCount() - queries);
}
