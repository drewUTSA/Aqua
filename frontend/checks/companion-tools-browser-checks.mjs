import assert from "node:assert/strict";

// Explicit opt-in journey: same bounded production-build fixture, no new traffic
// authority and no SQL/provider calls. Reports contain check names/counts only.
export async function runCompanionToolsChecks(ctx, { emailA, emailB, help }) {
  const { fixture, check, click, fill, waitFor, evaluate, navigate, signIn, viewport, screenshot } = ctx;
  const pause = () => new Promise((resolve) => setTimeout(resolve, 80));
  const open = async () => { await click("[data-open-companion]"); await waitFor("Boolean(document.querySelector('dialog[open]'))", "companion_dialog_open"); };
  const ready = () => waitFor("Boolean(document.querySelector('[data-companion-question]'))", "companion_menu_ready");
  const close = async () => { await click("[data-close-companion]"); await waitFor("!document.querySelector('dialog[open]')", "companion_dialog_closed"); };
  const read = async (text) => { await fill("[data-companion-question]", text); await click("[data-companion-read]"); };
  const held = async () => { const stop = performance.now() + 5500; while (!help.pending.length && performance.now() < stop) await pause(); assert.equal(help.pending.length, 1, "companion_one_bounded_read_held"); };
  fixture.email = null; fixture.canQuery = true; await viewport(1440, 900); await navigate("/signin"); await signIn(emailA);
  await waitFor("document.querySelector('.opal-composer textarea')?.disabled===false", "companion_composer_ready");
  await check("the Help launcher uses its visible text as its accessible name", "(()=>{const b=document.querySelector('[data-open-companion]');return b?.textContent.trim()==='Help'&&!b.hasAttribute('aria-label')&&!b.hasAttribute('aria-labelledby')})()");
  const before = fixture.queryCount();
  await fill(".opal-composer textarea", "Existing synthetic composer draft");
  await evaluate("window.__companionComposer=document.querySelector('.opal-composer textarea');true");

  help.enabled = false; await open();
  await waitFor("document.querySelector('[data-companion-error]')?.textContent.includes('not available on this server')", "companion_default_off_honest");
  await close(); await check("companion unavailable keeps composer node and draft", "document.querySelector('.opal-composer textarea')===window.__companionComposer&&window.__companionComposer.value==='Existing synthetic composer draft'");

  help.enabled = true; help.replyText = '<img src=x onerror="window.__fixtureScriptExecuted=1"> [unsafe](https://attacker.invalid)';
  await open(); await ready(); await read("reset password");
  await waitFor("Boolean(document.querySelector('[data-companion-answer]'))", "companion_cited_answer");
  await check("companion reviewed answer and citations are literal data", "document.querySelector('[data-companion-answer]').dataset.method==='reviewed_lookup'&&document.querySelector('[data-companion-message]').textContent.includes('<img')&&!document.querySelector('[data-companion-answer] img,[data-companion-answer] a')&&document.querySelector('[data-companion-answer] li').textContent.includes('Version: aaaaaaaaaaaa')&&document.querySelector('[data-companion-answer] [title]').title==='a'.repeat(64)&&window.__fixtureScriptExecuted===0");
  await check("companion dialog retains visible labels and 44px controls", "(()=>{const d=document.querySelector('.companion-tools-dialog');return d.open&&d.getAttribute('aria-labelledby')&&d.querySelector('label').htmlFor===d.querySelector('textarea').id&&[...d.querySelectorAll('button:not(:disabled),textarea')].every(el=>el.getBoundingClientRect().height>=43.5)})()");
  await evaluate("document.querySelector('[data-close-companion]').focus();document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));true");
  await check("companion tab boundary stays in the native dialog", "document.querySelector('.companion-tools-dialog').contains(document.activeElement)");
  await viewport(320, 640, true);
  await evaluate("document.querySelector('.opal-workspace').style.setProperty('--pref-text-scale','2');true");
  await check("companion 320px doubled text keeps close reachable without horizontal overflow", "(()=>{const d=document.querySelector('.companion-tools-dialog'),r=d.getBoundingClientRect(),b=d.querySelector('[data-close-companion]');b.scrollIntoView();return r.left>=-1&&r.right<=innerWidth+1&&d.scrollWidth<=d.clientWidth+1&&b.getBoundingClientRect().height>=44})()");
  await screenshot("companion-tools-320-double-text"); await viewport(1440, 900); await evaluate("document.querySelector('.opal-workspace').style.setProperty('--pref-text-scale','1');true");
  help.abstain = true; await read("unknown synthetic subject"); await waitFor("document.querySelector('[data-companion-answer] h3')?.textContent==='No clear guide found'", "companion_abstention");
  assert.equal(fixture.queryCount(), before); await close(); help.abstain = false;

  help.allowQuestion = false; await open(); await ready();
  await check("companion denied capability cannot prepare a question", "document.querySelector('[data-companion-mode=data]').disabled&&!document.querySelector('[data-companion-apply]')");
  await close(); help.allowQuestion = true; help.replyText = "Reviewed synthetic help.";
  await open(); await ready(); await click("[data-companion-mode=data]"); await fill("[data-companion-question]", "Count synthetic records by month"); await click("[data-companion-apply]");
  await waitFor("!document.querySelector('dialog[open]')", "companion_explicit_draft_applied");
  await check("companion explicit apply changes only existing composer draft", "document.querySelector('.opal-composer textarea')===window.__companionComposer&&window.__companionComposer.value==='Count synthetic records by month'");
  assert.equal(fixture.queryCount(), before, "companion_apply_did_not_submit");

  await open(); await ready(); await click("[data-companion-mode=data]"); await click("[data-companion-guide-mode=guided]");
  const guideCalls = help.calls.length;
  await click("[data-companion-guide-prepare]");
  await waitFor("document.querySelector('.companion-tools__guide-error')?.textContent==='Enter what you want to measure.'", "companion_guided_measure_required");
  await check("guided question preparation keeps the required measure visible and focused", "document.activeElement===document.querySelector('[data-companion-guide-field=measure]')&&document.querySelector('[data-companion-apply]').disabled");
  await fill("[data-companion-guide-field=measure]", "Total synthetic amounts"); await click("[data-companion-guide-prepare]");
  await check("guided question preview marks missing details without invented time units or schema", "(()=>{const q=document.querySelector('[data-companion-question]').value;return q.includes('Measure: Total synthetic amounts')&&['Grouping','Time period','Filters'].every(label=>q.includes(label+': Not specified.'))&&q.includes('Do not invent omitted details, definitions or units.')&&!q.includes('Ask me to clarify')&&!q.includes('USD')&&!q.includes('SELECT')&&window.__companionComposer.value==='Count synthetic records by month'})()");
  await fill("[data-companion-guide-field=grouping]", "Synthetic category");
  await check("editing guided fields requires another explicit preparation before apply", "document.querySelector('[data-companion-apply]').disabled&&!document.querySelector('[data-companion-question]').value.includes('Synthetic category')");
  await fill("[data-companion-guide-field=period]", "January 2030"); await fill("[data-companion-guide-field=filters]", "Synthetic status is active");
  await click("[data-companion-guide-prepare]");
  await check("guided review contains only the supplied measure grouping period and filters", "(()=>{const q=document.querySelector('[data-companion-question]').value;return q.includes('Measure: Total synthetic amounts')&&q.includes('Grouping: Synthetic category')&&q.includes('Time period: January 2030')&&q.includes('Filters: Synthetic status is active')&&!document.querySelector('[data-companion-apply]').disabled})()");
  await viewport(320, 844, true); await evaluate("document.querySelector('.opal-workspace').style.setProperty('--pref-text-scale','2');true");
  const guidedGeometry = await evaluate("(()=>{const d=document.querySelector('.companion-tools-dialog'),r=d.getBoundingClientRect(),fields=[...d.querySelectorAll('[data-companion-guide-field]')];return {viewport:innerWidth,left:r.left,right:r.right,scrollWidth:d.scrollWidth,clientWidth:d.clientWidth,fieldCount:fields.length,fields:fields.slice(0,4).map(input=>({height:input.getBoundingClientRect().height,fontSize:parseFloat(getComputedStyle(input).fontSize),labels:input.labels.length}))}})()");
  process.stdout.write(JSON.stringify({ synthetic_guided_geometry: guidedGeometry }) + "\n");
  await check("guided question fields retain labels 44px targets and narrow doubled-text reflow", "(()=>{const d=document.querySelector('.companion-tools-dialog'),r=d.getBoundingClientRect();return r.left>=-1&&r.right<=innerWidth+1&&d.scrollWidth<=d.clientWidth+1&&[...d.querySelectorAll('[data-companion-guide-field]')].every(input=>input.labels.length===1&&input.getBoundingClientRect().height>=44&&parseFloat(getComputedStyle(input).fontSize)>=31)})()");
  await screenshot("companion-guided-draft-320-double-text"); await viewport(1440, 900); await evaluate("document.querySelector('.opal-workspace').style.setProperty('--pref-text-scale','1');window.__companionGuidedDraft=document.querySelector('[data-companion-question]').value;true");
  assert.equal(help.calls.length, guideCalls, "guided_preparation_made_no_help_or_provider_request");
  assert.equal(fixture.queryCount(), before, "guided_preview_did_not_submit");
  await click("[data-companion-apply]"); await waitFor("!document.querySelector('dialog[open]')", "companion_guided_draft_explicitly_applied");
  await check("guided apply updates only the same composer and does not send analysis", "document.querySelector('.opal-composer textarea')===window.__companionComposer&&window.__companionComposer.value===window.__companionGuidedDraft");
  assert.equal(fixture.queryCount(), before, "guided_apply_did_not_submit");

  await open(); await ready(); await click("[data-companion-mode=data]"); await fill("[data-companion-question]", "Do not overwrite a newer draft");
  await check("a closed guide is not persisted and free-form questions remain available", "document.querySelector('[data-companion-guide-mode=free]').getAttribute('aria-pressed')==='true'&&!document.querySelector('[data-companion-guide-field]')");
  await fill(".opal-composer textarea", "Newer synthetic composer draft"); await click("[data-companion-apply]");
  await waitFor("document.querySelector('[data-companion-error]')?.textContent.includes('composer draft changed')", "companion_draft_conflict");
  await close(); await check("companion changed draft is preserved", "window.__companionComposer.value==='Newer synthetic composer draft'");

  help.hold = true; help.replyText = "OLD-COMPANION-ANSWER"; await open(); await ready(); await read("first held read"); await held(); await close(); await help.release(); await pause();
  await check("companion close discards held read without remounting composer", "!document.querySelector('[data-companion-answer]')&&document.querySelector('.opal-composer textarea')===window.__companionComposer");
  await open(); await ready(); await read("older held read"); await held();
  help.hold = false; help.replyText = "NEW-COMPANION-ANSWER"; await read("newer explicit read");
  await waitFor("document.querySelector('[data-companion-message]')?.textContent==='NEW-COMPANION-ANSWER'", "companion_new_read_visible");
  await help.release(); await pause(); await check("companion newer read rejects old completion", "document.querySelector('[data-companion-message]').textContent==='NEW-COMPANION-ANSWER'"); await close();

  help.hold = true; await open(); await ready(); await read("history boundary read"); await held(); help.historyRevision = "b".repeat(64); await help.release();
  await waitFor("!document.querySelector('.companion-tools-dialog')", "companion_history_change_closed");
  await check("companion history change clears private help", "!document.querySelector('[data-companion-answer]')");
  help.historyRevision = null; help.hold = false; await navigate("/");
  await waitFor("Boolean(document.querySelector('[data-open-companion]'))", "companion_workspace_reloaded");
  help.hold = true; await open(); await ready(); await read("old owner held read"); await held();
  fixture.email = null; await navigate("/signin"); await signIn(emailB); await help.release(); help.hold = false; await pause();
  await check("companion owner switch cannot restore previous help", "!document.querySelector('.companion-tools-dialog,[data-companion-answer]')&&!document.body.textContent.includes('OLD-COMPANION-ANSWER')");
  await open(); await ready(); help.hold = true; await read("settings boundary held read"); await held();
  await evaluate("history.pushState({},'', '/settings');window.dispatchEvent(new PopStateEvent('popstate'));true");
  await waitFor("Boolean(document.querySelector('.settings-shell'))&&!document.querySelector('.companion-tools-dialog')", "companion_settings_unmounted");
  await help.release(); help.hold = false;

  help.blockChunk = true; await navigate("/"); await waitFor("Boolean(document.querySelector('[data-open-companion]'))", "companion_chunk_failure_workspace_ready");
  await fill(".opal-composer textarea", "Draft preserved through optional chunk failure");
  await evaluate("window.__companionComposer=document.querySelector('.opal-composer textarea');true"); await open();
  await waitFor("document.querySelector('dialog[open] h2')?.textContent==='Aqua tools unavailable'", "companion_optional_chunk_failure_contained");
  await click("dialog[open] button"); await waitFor("!document.querySelector('dialog[open]')", "companion_failed_chunk_close");
  await check("companion optional download failure keeps draft and composer", "document.querySelector('.opal-composer textarea')===window.__companionComposer&&window.__companionComposer.value==='Draft preserved through optional chunk failure'");
  help.blockChunk = false; assert.equal(fixture.queryCount(), before, "companion_journey_never_submitted_sql");
  assert.equal(help.pending.length, 0); return { checks: "reviewed_help_explicit_draft_and_adverse_lifecycles", help_requests: help.calls.length, analytical_submissions: 0, held_reads_remaining: 0, guided_geometry: guidedGeometry };
}
