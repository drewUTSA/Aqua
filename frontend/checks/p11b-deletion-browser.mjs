import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { BrowserPipe } from './p05-browser-pipe.mjs';
const root = fileURLToPath(new URL('..', import.meta.url));
const artifact = process.env.AQUA_DELETION_ARTIFACT_DIR || path.resolve(root, '../.check-results/p11b-frontend');
let server, browser, cdp, sessionId, profile, denyContent = false; const checks = [], errors = [];
try {
  server = await createServer({ root, configFile: false, server: { host: '127.0.0.1', port: 0, strictPort: true }, plugins: [{ name: 'deletion-ui-fixture', configureServer(instance) {
    instance.middlewares.use((request, response, next) => {
      if (denyContent && request.url.split('?')[0] === '/src/settings/DataDeletionContent.jsx') {
        denyContent = false; response.writeHead(503, { 'Content-Type': 'text/javascript', 'Cache-Control': 'no-store' }); response.end(''); return;
      }
      if (request.url.split('?')[0] !== '/') return next();
      response.setHeader('Content-Type', 'text/html'); response.end('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Deletion fixture</title></head><body><div id="root"></div><script type="module" src="/checks/deletion-browser-fixture.jsx"></script></body></html>');
    });
  } }] });
  await server.listen(); const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  profile = await mkdtemp(path.join(tmpdir(), 'aqua-deletion-ui-'));
  browser = spawn(process.env.AQUA_CHROME_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-extensions', '--disable-default-apps', '--no-pings', '--metrics-recording-only', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1', '--remote-debugging-pipe', `--user-data-dir=${profile}`, 'about:blank'], { stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
  cdp = new BrowserPipe(browser, { session: () => sessionId, deadline: performance.now() + 90000 });
  await cdp.ready(); const targets = await cdp.send('Target.getTargets');
  ({ sessionId } = await cdp.send('Target.attachToTarget', { targetId: targets.targetInfos.find(item => item.type === 'page').targetId, flatten: true }));
  cdp.onEvent = event => { if (event.sessionId === sessionId && event.method === 'Runtime.exceptionThrown') errors.push('runtime_exception'); };
  await cdp.send('Runtime.enable'); await cdp.send('Page.enable');
  const evaluate = async expression => { const result = await cdp.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (result.exceptionDetails) throw Error('fixture_evaluation_failed'); return result.result.value; };
  const wait = async (expression, label) => { const until = performance.now() + 6000; while (performance.now() < until) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 25)); } console.error(JSON.stringify(await evaluate('({phase:document.querySelector("[data-deletion-phase]")?.dataset.deletionPhase,buttons:[...document.querySelectorAll("dialog button")].map(button=>({text:button.textContent,disabled:button.disabled})),dialogOpen:!!document.querySelector("dialog[open]"),counts:window.deletionFixture?.counts()})'))); throw Error(label); };
  const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
  const phase = value => `document.querySelector('[data-deletion-phase]')?.dataset.deletionPhase===${JSON.stringify(value)}`;
  const fill = (selector, value) => evaluate(`(()=>{const input=document.querySelector(${JSON.stringify(selector)});Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,${JSON.stringify(value)});input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  const start = async (scenario, account = false) => {
    await cdp.send('Page.navigate', { url: origin + '/?scenario=' + scenario });
    await wait('!!document.querySelector("[data-private-draft]")', 'fixture_ready');
    await fill('[data-private-draft]', 'OLD PRIVATE DRAFT');
    await click(account ? '[data-open-account]' : '[data-open-history]');
    await wait('!!document.querySelector("dialog[open]") && [...document.querySelectorAll("button")].some(button=>button.textContent==="Continue to verification"&&!button.disabled)', 'review_ready');
    assert.equal(await evaluate('document.querySelector("dialog").textContent.includes("cannot be undone")'), true);
    await evaluate('[...document.querySelectorAll("dialog button")].find(button=>button.textContent==="Continue to verification").click()');
    await wait(phase('verify'), 'verify_ready');
    await fill('[data-account-current-password]', 'Synthetic verification password 27');
    await evaluate('document.querySelector("[data-account-current-password]").form.requestSubmit()');
    await wait(phase('confirm'), 'confirm_ready');
    await fill('dialog input', 'WRONG CONFIRMATION'); await evaluate('document.querySelector("dialog form").requestSubmit()');
    assert.equal(await evaluate('deletionFixture.counts().creates'), 0);
    await fill('dialog input', account ? 'DELETE ACCOUNT' : 'DELETE HISTORY'); await evaluate('document.querySelector("dialog form").requestSubmit()');
  };
  // A failed optional review chunk must leave the existing private workspace
  // intact and provide a focused safe close, without any proof or deletion.
  await cdp.send('Page.navigate', { url: origin + '/?scenario=history' });
  await wait('!!document.querySelector("[data-private-draft]")', 'failed_review_fixture_ready');
  await fill('[data-private-draft]', 'OLD PRIVATE DRAFT'); denyContent = true;
  await click('[data-open-history]');
  await wait('document.querySelector("dialog [role=alert]")?.textContent.includes("review is unavailable")', 'failed_review_is_closed');
  assert.equal(await evaluate('document.activeElement===document.querySelector("dialog button")'), true);
  assert.equal(await evaluate('document.querySelector("[data-private-draft]").value'), 'OLD PRIVATE DRAFT');
  assert.deepEqual(await evaluate('deletionFixture.counts()'), { creates: 0, reconciles: 0, verifications: 0, invalid: 0, external: 0 });
  await click('dialog button'); await wait('!document.querySelector("dialog")', 'failed_review_closed');
  checks.push('failed_review_chunk_preserves_workspace_and_safe_focused_close_without_mutation');

  await start('history'); await wait(phase('observing'), 'history_accepted');
  assert.equal(await evaluate('document.querySelector("[data-deletion-state]").dataset.deletionState'), 'accepted');
  await wait('!!document.querySelector("[data-private-draft]")', 'history_remounted');
  assert.equal(await evaluate('document.querySelector("[data-private-draft]").value'), '');
  assert.equal(await evaluate('deletionFixture.receiptPresentInStorage()'), false);
  await mkdir(artifact, { recursive: true });
  const screenshot = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(path.join(artifact, 'history-accepted.png'), Buffer.from(screenshot.data, 'base64'));
  checks.push('typed_confirmation_and_history_remount');

  await start('history-uncertain'); await wait(phase('uncertain'), 'history_uncertain');
  assert.equal(await evaluate('document.querySelector("[data-private-draft]")?.value || ""'), '');
  await click('[data-check-deletion-receipt]'); await wait(phase('observing'), 'history_waiting_authority');
  assert.equal(await evaluate('document.querySelector("[data-deletion-state]").dataset.deletionState'), 'awaiting_authority');
  assert.equal(await evaluate('deletionFixture.counts().creates'), 1);
  await evaluate('deletionFixture.state("complete")'); await click('[data-check-deletion-receipt]'); await wait('document.querySelector("[data-deletion-state]")?.dataset.deletionState==="complete"', 'history_cleanup_confirmed');
  assert.deepEqual(await evaluate('deletionFixture.counts()'), { creates: 1, reconciles: 2, verifications: 1, invalid: 0, external: 0 });
  checks.push('uncertain_history_reconciles_without_replay');

  await start('account-uncertain', true); await wait(phase('uncertain'), 'account_uncertain');
  assert.equal(await evaluate('document.querySelector("[data-auth-state]").textContent'), 'signedout');
  assert.equal(await evaluate('!!document.querySelector("[data-private-content]")'), false);
  assert.equal(await evaluate('!!document.querySelector("[data-deletion-state]")'), false);
  await evaluate('deletionFixture.state("accepted")'); await click('[data-check-deletion-receipt]'); await wait(phase('observing'), 'revoked_account_receipt');
  assert.equal(await evaluate('document.querySelector("[data-deletion-state]").dataset.deletionState'), 'accepted');
  assert.equal(await evaluate('deletionFixture.counts().creates'), 1);
  await evaluate('deletionFixture.login()'); await wait('!document.querySelector("dialog")', 'new_login_clears_receipt');
  assert.equal(await evaluate('document.querySelector("[data-private-draft]").value'), '');
  checks.push('account_uncertainty_receipt_survives_local_revocation_and_clears_on_login');

  await start('account-uncertain', true); await wait(phase('uncertain'), 'close_receipt_ready');
  await evaluate('[...document.querySelectorAll("dialog button")].find(button=>button.textContent==="Close receipt").click()');
  await wait('!document.querySelector("dialog")', 'receipt_closed');
  assert.deepEqual(await evaluate('deletionFixture.counts()'), { creates: 1, reconciles: 0, verifications: 1, invalid: 0, external: 0 });
  checks.push('close_discards_uncertain_receipt_without_new_mutation');

  await cdp.send('Page.navigate', { url: origin + '/?scenario=expire' });
  await wait('document.querySelector("[data-auth-state]")?.textContent==="authenticated" && !!document.querySelector("[data-open-history]")', 'expiry_fixture_ready'); await click('[data-open-history]');
  await wait(phase('expired'), 'receipt_expired');
  await new Promise(resolve => setTimeout(resolve, 75));
  assert.equal(await evaluate('document.querySelectorAll("dialog").length'), 1);
  assert.deepEqual(await evaluate('deletionFixture.counts()'), { creates: 0, reconciles: 0, verifications: 0, invalid: 0, external: 0 });
  await evaluate('document.querySelector("dialog button").click()'); await wait('!document.querySelector("dialog")', 'expired_receipt_closed');
  checks.push('expiry_clears_receipt_without_repeating_render_or_mutation');
  assert.deepEqual(errors, []);
} finally {
  // Every owned resource gets a cleanup attempt, even if an earlier close fails.
  try {
    if (cdp) await cdp.stop(); else browser?.kill('SIGKILL');
  } finally {
    try { await server?.close(); }
    finally { if (profile) await rm(profile, { recursive: true, force: true }); }
  }
}
// BrowserPipe.stop records abnormal/forced/incomplete cleanup without throwing.
// Success evidence must follow cleanup and require the actual drain result.
assert.equal(cdp?.stopped, true, 'browser_cleanup_not_stopped');
assert.equal(cdp?.drained, true, 'browser_cleanup_not_drained');
assert.equal(cdp?.cleanupFailure, null, 'browser_cleanup_failed');
assert.equal(checks.length, 6, 'deletion_check_count_changed');
const report = { status: 'passed', mode: 'synthetic_frontend_chrome_only', checks, production_or_provider_calls: 0 };
await writeFile(path.join(artifact, 'browser-report.json'), JSON.stringify(report, null, 2) + '\n'); console.log(JSON.stringify(report));
