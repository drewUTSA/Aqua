// Real Settings UI and current-owner API over a disposable PostgreSQL fixture.
import { checkAppearancePresets, checkMobileCategories, checkSettingsAccessibilityTree } from './p09-appearance-checks.mjs';
const q = JSON.stringify;
const endpoint = '/api/v1/me/preferences';
const field = key => '#settings-field-' + key;
const saveDisabled = "[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='Save changes')?.disabled===true";

export async function runPreferenceChecks(ctx) {
  const { check, evaluate, waitFor, click, clickText } = ctx;
  async function preferences() {
    const response = await ctx.rawRequest('GET', endpoint);
    if (response.status !== 200) throw Error('preference_read_failed');
    return JSON.parse(response.body);
  }
  async function select(key, value) {
    const selector = field(key);
    await waitFor(`Boolean(document.querySelector(${q(selector)}))&&!document.querySelector(${q(selector)}).disabled`, 'preference_select_ready');
    await evaluate(`(()=>{const el=document.querySelector(${q(selector)});el.focus();Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(el,${q(value)});el.dispatchEvent(new Event('change',{bubbles:true}));return true})()`);
  }
  async function enterSettings() {
    ctx.navigating = true;
    try {
      await ctx.cdp.send('Page.navigate', { url: 'about:blank' });
      await waitFor("location.href==='about:blank'", 'settings_navigation_reset');
      await ctx.cdp.send('Page.navigate', { url: ctx.origin + '/settings' });
      await waitFor("Boolean(document.querySelector('#settings-heading'))&&Boolean(document.querySelector('#settings-field-accent'))&&!document.querySelector('#settings-field-accent').disabled", 'settings_account_ready');
    } finally { ctx.navigating = false; }
  }
  async function importText(text) {
    await evaluate(`(()=>{const input=document.querySelector('#settings-import-file');if(!input)throw Error();const transfer=new DataTransfer();transfer.items.add(new File([${q(text)}],'preferences.json',{type:'application/json'}));input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));return true})()`);
  }
  const original = await preferences();
  await enterSettings();
  await check('Settings loads for an authenticated account without dataset grants', "document.querySelector('#settings-heading').textContent==='Settings'&&!document.querySelector('#settings-field-accent').disabled");
  await checkSettingsAccessibilityTree(ctx);
  await checkAppearancePresets(ctx);
  if ((await preferences()).revision !== original.revision) throw Error('appearance_preview_saved_without_action');
  const unsavedAccent = original.values.accent === 'sage' ? 'amber' : 'sage';
  await select('accent', unsavedAccent);
  await waitFor('!(' + saveDisabled + ')', 'account_preference_dirty');
  await clickText('Cancel changes');
  await check('Cancel restores the account value and clears the dirty state', `document.querySelector('${field('accent')}').value===${q(original.values.accent)}&&(${saveDisabled})`);
  if ((await preferences()).revision !== original.revision) throw Error('cancel_mutated_saved_revision');
  ctx.results.push({ check: 'Cancel makes no account write', passed: true });
  await select('accent', unsavedAccent); await clickText('Save changes');
  await waitFor("document.querySelector('.settings-shell').textContent.includes('Account preferences saved.')", 'account_save_confirmed');
  const saved = await preferences();
  if (saved.revision !== original.revision + 1 || saved.values.accent !== unsavedAccent) throw Error('save_revision_or_value_invalid');
  await enterSettings();
  await check('Saved account preferences survive a full document reload', `document.querySelector('${field('accent')}').value===${q(unsavedAccent)}`);

  // Simulate another authorized tab through the real API, then submit the old
  // editor revision. A conflict must retain the unsaved draft without overwriting.
  const authResponse = await ctx.rawRequest('GET', '/api/auth/me');
  const csrf = JSON.parse(authResponse.body).csrf_token;
  if (typeof csrf !== 'string') throw Error('csrf_fixture_unavailable');
  const externalAccent = unsavedAccent === 'amber' ? 'pearl' : 'amber';
  const changed = await ctx.rawRequest('PUT', endpoint, { schemaVersion: 1, expectedRevision: saved.revision, values: { ...saved.values, accent: externalAccent } }, csrf);
  if (changed.status !== 200) throw Error('second_context_write_failed');
  await select('accent', 'slate'); await clickText('Save changes');
  await waitFor("Boolean(document.querySelector('[role=alert]'))&&document.querySelector('.settings-shell').textContent.includes('Reload')", 'stale_revision_reported');
  await check('A stale editor retains its draft after a real revision conflict', "document.querySelector('#settings-field-accent').value==='slate'");
  if ((await preferences()).values.accent !== externalAccent) throw Error('stale_save_overwrote_newer_preferences');
  await clickText('Cancel changes');
  await enterSettings();
  await click("[data-settings-category='privacy']");
  const beforeImport = await preferences();
  await evaluate("(()=>{const blobs=new Map(),create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL),click=HTMLAnchorElement.prototype.click;window.__p09Export='';URL.createObjectURL=blob=>{const url=create(blob);blobs.set(url,blob);return url;};URL.revokeObjectURL=url=>{blobs.delete(url);revoke(url);};HTMLAnchorElement.prototype.click=function(){const blob=blobs.get(this.href);if(this.download==='aqua-preferences-v1.json'&&blob){void blob.text().then(text=>{window.__p09Export=text;});return;}return click.call(this);};return true})()");
  const invalid = [
    '{"schemaVersion":99,"account":{}}',
    '{"schemaVersion":1,"account":{"__proto__":{"admin":true}}}',
    '{"schemaVersion":1,"account":{"can_query":true}}',
    '{"schemaVersion":1,"account":{"precision":2}}',
    ' '.repeat(65537)
  ];
  for (const text of invalid) {
    await importText(text);
    await waitFor("Boolean(document.querySelector('.settings-error[role=alert]'))", 'invalid_import_rejected');
    await check('Invalid preference import is rejected before comparison or application', "!document.querySelector('dialog[open]')&&({}).admin===undefined");
  }
  if ((await preferences()).revision !== beforeImport.revision) throw Error('invalid_import_mutated_saved_preferences');
  await importText(JSON.stringify({ schemaVersion: 1, account: { accent: 'slate' }, device: { motion: 'reduce' } }));
  await waitFor("document.querySelector('dialog[open]')?.textContent.includes('Review preference import')", 'safe_import_comparison');
  await check('Import comparison receives focus inside its modal', "document.querySelector('dialog[open]').contains(document.activeElement)");
  await clickText('Apply to draft', 'dialog button');
  if ((await preferences()).revision !== beforeImport.revision) throw Error('import_applied_before_save');
  await clickText('Export preferences');
  await waitFor("window.__p09Export.length>0", 'saved_preference_export_created');
  await check('Export contains only saved allowlisted preferences and excludes the unsaved draft', `(()=>{const value=JSON.parse(window.__p09Export);return value.schemaVersion===1&&Object.keys(value).sort().join(',')==='account,schemaVersion'&&value.account.accent===${q(beforeImport.values.accent)}&&!Object.keys(value.account).some(key=>/email|password|token|cookie|session|owner|user_id|can_query|consent|chat_data/.test(key))})()`);
  await clickText('Save changes');
  await waitFor("document.querySelector('.settings-shell').textContent.includes('Account preferences saved.')", 'import_saved_explicitly');
  if ((await preferences()).values.accent !== 'slate') throw Error('safe_import_not_saved');
  await click("[data-settings-category='appearance']");
  await check('Reviewed import applies its account value after explicit Save', "document.querySelector('#settings-field-accent').value==='slate'");
  await clickText('Reset this section');
  await waitFor("Boolean(document.querySelector('dialog[open]'))", 'reset_confirmation_open');
  await ctx.cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9, modifiers: 8 });
  await ctx.cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9, modifiers: 8 });
  await check('Keyboard traversal stays inside the reset dialog', "document.querySelector('dialog[open]').contains(document.activeElement)");
  await ctx.cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 });
  await ctx.cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 });
  await waitFor("!document.querySelector('dialog[open]')", 'escape_cancels_reset');
  await check('Escape cancels reset and restores focus to its trigger', "document.activeElement.textContent.trim()==='Reset this section'&&document.querySelector('#settings-field-accent').value==='slate'");
  await ctx.screenshot('settings-desktop');
  await ctx.cdp.send('Emulation.setDeviceMetricsOverride', { width: 320, height: 844, deviceScaleFactor: 1, mobile: false });
  const beforeText = await evaluate("({root:parseFloat(getComputedStyle(document.documentElement).fontSize),select:parseFloat(getComputedStyle(document.querySelector('#settings-field-accent')).fontSize)})");
  await evaluate("(async()=>{document.documentElement.style.fontSize='200%';await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));return true})()");
  const afterText = await evaluate("({root:parseFloat(getComputedStyle(document.documentElement).fontSize),select:parseFloat(getComputedStyle(document.querySelector('#settings-field-accent')).fontSize)})");
  ctx.mobileTextAudit = { before_pixels: beforeText, after_pixels: afterText, actual_select_scale: afterText.select / beforeText.select };
  if (ctx.mobileTextAudit.actual_select_scale < 1.99) throw Error('settings_text_did_not_double');
  ctx.results.push({ check: 'Computed Settings control text actually doubles at 200% root size', passed: true });
  await check('Settings Save remains reachable at 320px with doubled root text', "(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='Save changes');b.scrollIntoView({block:'center'});const r=b.getBoundingClientRect();return r.width>0&&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight})()");
  await ctx.screenshot('settings-320-double-text');
  await checkMobileCategories(ctx);
  return { saved_revision: (await preferences()).revision, invalid_import_cases: invalid.length, analysis_jobs_requested: 0 };
}
