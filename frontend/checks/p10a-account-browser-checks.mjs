// Real account endpoints and current-owner UI in the disposable auth fixture.
// The observer can hold or drop a real completed response; it never fabricates
// account DTOs, grants access, starts analysis or changes the server response.
const q = JSON.stringify;
const nameInput = '[data-account-name-input]';
const dialog = '.account-name-dialog[open]';
const saveDisabled = "[...document.querySelectorAll('.settings-savebar button')].find(e=>e.textContent.trim()==='Save changes')?.disabled===true";

export async function runAccountChecks(ctx) {
  const { check, evaluate, waitFor, click, clickText, fill } = ctx;
  const auth = await ctx.rawRequest('GET', '/api/auth/me');
  const session = JSON.parse(auth.body);
  if (auth.status !== 200 || session.can_query !== false || typeof session.csrf_token !== 'string') throw Error('account_fixture_identity_invalid');
  ctx.secrets.add(session.csrf_token);
  const observer = `(()=>{
    const perform=window.fetch.bind(window);window.__accountAudit=[];window.__accountLoseName=false;window.__accountHoldProfile=false;window.__accountHoldAuth=false;
    window.fetch=(resource,options={})=>{
      const url=new URL(typeof resource==='string'?resource:resource.url,location.href),method=(options.method||'GET').toUpperCase();
      const account=url.origin===location.origin&&/^\\/api\\/v1\\/me(?:\\/(?:methods|sessions))?$/.test(url.pathname);
      const event={route:url.pathname,method,aborted:false};
      if(account){window.__accountAudit.push(event);options.signal?.addEventListener('abort',()=>{event.aborted=true},{once:true});}
      return perform(resource,options).then(response=>{
        if(url.origin===location.origin&&url.pathname==='/api/auth/me'&&method==='GET'&&window.__accountHoldAuth){window.__accountHoldAuth=false;return new Promise(resolve=>{window.__accountAuthRelease=()=>{delete window.__accountAuthRelease;resolve(response);};});}
        if(account&&method==='PATCH'&&response.status===200&&window.__accountLoseName){window.__accountLoseName=false;throw new TypeError('Synthetic lost account response');}
        if(account&&url.pathname==='/api/v1/me'&&method==='GET'&&window.__accountHoldProfile){window.__accountHoldProfile=false;window.__accountHeldEvent=event;return new Promise(resolve=>{window.__accountRelease=()=>{delete window.__accountRelease;resolve(response);};});}
        return response;
      });
    };return true;
  })()`;
  await ctx.cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: observer });
  await ctx.navigate('/');
  await waitFor("Boolean(document.querySelector('.opal-workspace'))&&!document.querySelector('.opal-workspace').closest('[hidden],[inert]')", 'workspace_account_observer_ready');
  await check('Account journey uses the requested production shell', `document.querySelector('.opal-workspace')?.dataset.uiShell===${q(process.env.AQUA_P05_EXPECTED_SHELL || 'opal')}`);
  await check('Home does not eagerly request profile, methods or sessions', 'window.__accountAudit.length===0');
  await ctx.navigate('/settings');
  await waitFor("document.querySelector('#settings-field-accent')?.disabled===false", 'settings_ready');
  await check('Appearance does not request profile, methods or sessions', 'window.__accountAudit.length===0');
  const accent = await evaluate("document.querySelector('#settings-field-accent').value");
  const draftAccent = accent === 'sage' ? 'amber' : 'sage';
  await evaluate(`(()=>{const el=document.querySelector('#settings-field-accent');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(el,${q(draftAccent)});el.dispatchEvent(new Event('change',{bubbles:true}));return true})()`);
  await waitFor('!(' + saveDisabled + ')', 'independent_preference_draft_ready');
  await click('[data-settings-category="account"]');
  await waitFor("Boolean(document.querySelector('[data-account-profile]'))", 'account_profile_loaded');
  await check('Account profile is verified while analytical access remains absent', `document.querySelector('[data-account-primary-email]')?.textContent===${q(session.user.email)}&&document.querySelector('[data-account-profile]').textContent.includes('Verified')`);
  await check('Account entry requests one profile and no method or session list', "window.__accountAudit.length===1&&window.__accountAudit[0].route==='/api/v1/me'&&window.__accountAudit[0].method==='GET'");
  const originalName = await evaluate("document.querySelector('[data-account-saved-name]').textContent");
  await click('[data-account-edit-name]');
  await waitFor(`Boolean(document.querySelector(${q(dialog)}))`, 'name_dialog_open');
  await check('Name editing uses a labelled native modal with an independent save', `document.querySelector(${q(dialog)})?.tagName==='DIALOG'&&Boolean(document.querySelector(${q(dialog)})?.getAttribute('aria-labelledby'))&&document.querySelector('[data-account-save-name]')?.textContent==='Save name'`);
  await fill(nameInput, 'Cancelled account edit');
  await clickText('Cancel', dialog + ' button');
  await check('Cancel retains saved identity and independent preference draft without a write', `!document.querySelector(${q(dialog)})&&document.querySelector('[data-account-saved-name]').textContent===${q(originalName)}&&window.__accountAudit.every(e=>e.method!=='PATCH')&&!(${saveDisabled})`);
  await click('[data-account-edit-name]');
  await fill(nameInput, '  Jose\u0301 <img src=x>  ');
  await click('[data-account-save-name]');
  await waitFor("!document.querySelector('.account-name-dialog[open]')&&document.querySelector('[data-account-saved-name]')?.textContent==='José <img src=x>'", 'name_save_confirmed');
  await check('Canonical name normalization renders markup as inert plain text', "document.querySelector('[data-account-saved-name]')?.textContent==='José <img src=x>'&&!document.querySelector('[data-account-saved-name] img')");
  await waitFor("Boolean(document.querySelector('.opal-workspace'))&&!document.querySelector('.opal-workspace').closest('[hidden],[inert]')", 'same_owner_refresh_ready');
  const confirmedAuth = await ctx.rawRequest('GET', '/api/auth/me');
  if (confirmedAuth.status !== 200 || JSON.parse(confirmedAuth.body).user.name !== 'José <img src=x>' || JSON.parse(confirmedAuth.body).user.id !== session.user.id) throw Error('name_session_refresh_unconfirmed');
  await check('Confirmed name refresh keeps the same-owner presentation draft dirty', '!(' + saveDisabled + ')');
  await click('[data-settings-category="appearance"]');
  await check('Same-owner auth refresh retains the exact unsaved preference value', `document.querySelector('#settings-field-accent')?.value===${q(draftAccent)}&&!(${saveDisabled})`);
  await click('[data-settings-category="account"]');
  await waitFor("document.querySelector('[data-account-saved-name]')?.textContent==='José <img src=x>'", 'canonical_profile_reloaded');
  await click('[data-account-load-methods]');
  await waitFor("Boolean(document.querySelector('[data-account-methods]'))", 'method_list_loaded');
  await check('Actual linked password and unlinked Google are distinguished without management controls', "document.querySelector('[data-account-methods]').textContent.includes('PasswordLinked')&&document.querySelector('[data-account-methods]').textContent.includes('GoogleNot linked')&&!document.querySelector('[data-account-methods] button')");
  await click('[data-account-load-sessions]');
  await waitFor("Boolean(document.querySelector('[data-account-sessions]'))", 'session_list_loaded');
  await check('Current session is bounded and read-only with no invented location or MFA', "document.querySelectorAll('.account-session').length>=1&&document.querySelectorAll('.account-session').length<=20&&document.querySelectorAll('.account-current').length===1&&!document.querySelector('[data-account-sessions] button')&&!/IP address|MFA|verified location/.test(document.querySelector('[data-account-sessions]').textContent)");
  await check('Unavailable security mutations have no enabled controls', "![...document.querySelectorAll('[data-account-foundation] button')].some(e=>!e.disabled&&/change email|change password|revoke|unlink|link google|verify identity/i.test(e.textContent))");
  const latestResponse = await ctx.rawRequest('GET', '/api/v1/me'), latest = JSON.parse(latestResponse.body);
  if (latestResponse.status !== 200) throw Error('account_canonical_read_failed');
  await click('[data-account-edit-name]');
  await fill(nameInput, 'My retained account edit');
  const concurrent = await ctx.rawRequest('PATCH', '/api/v1/me', { expectedRevision: latest.revision, display_name: 'Other authorized tab' }, session.csrf_token);
  if (concurrent.status !== 200) throw Error('account_concurrent_write_failed');
  await click('[data-account-save-name]');
  await waitFor("Boolean(document.querySelector('[data-account-reconcile]'))", 'account_conflict_preserved');
  await check('CAS conflict retains the entered name and blocks blind retry', "document.querySelector('[data-account-name-input]')?.value==='My retained account edit'&&document.querySelector('[data-account-save-name]').disabled===true");
  await click('[data-account-reconcile]');
  await waitFor("Boolean(document.querySelector('[data-account-keep-edit]'))", 'latest_account_name_reviewed');
  await check('Reload presents canonical name while preserving the unsaved edit', "document.querySelector('.account-name-review').textContent.includes('Other authorized tab')&&document.querySelector('[data-account-name-input]').value==='My retained account edit'&&document.querySelector('[data-account-save-name]').disabled===true");
  await click('[data-account-keep-edit]');
  await click('[data-account-save-name]');
  await waitFor("!document.querySelector('.account-name-dialog[open]')&&document.querySelector('[data-account-saved-name]')?.textContent==='My retained account edit'", 'reviewed_account_save_confirmed');
  await waitFor("document.querySelector('[data-account-edit-name]')?.disabled===false", 'reviewed_save_auth_ready');
  await click('[data-account-edit-name]');
  await fill(nameInput, 'Response reconciled name');
  await evaluate('window.__accountLoseName=true');
  await click('[data-account-save-name]');
  await waitFor("Boolean(document.querySelector('[data-account-reconcile]'))", 'lost_response_preserved');
  await check('A lost real write response preserves text without claiming a confirmed save', "document.querySelector('[data-account-name-input]').value==='Response reconciled name'&&document.querySelector('[data-account-save-name]').disabled===true&&document.querySelector('[data-account-saved-name]').textContent==='My retained account edit'");
  const patches = await evaluate("window.__accountAudit.filter(e=>e.method==='PATCH').length");
  await click('[data-account-reconcile]');
  await waitFor("document.querySelector('.account-name-dialog[open]')?.textContent.includes('Your saved name is confirmed.')", 'lost_response_get_confirmed');
  await check('Reconciliation confirms the saved result through GET without replaying PATCH', `document.querySelector('[data-account-saved-name]').textContent==='Response reconciled name'&&window.__accountAudit.filter(e=>e.method==='PATCH').length===${patches}`);
  await clickText('Done', dialog + ' button');
  await waitFor("document.querySelector('[data-account-edit-name]')?.disabled===false", 'reconciled_auth_ready');
  await click('[data-account-edit-name]');
  await fill(nameInput, 'Draft retained while checking sign-in');
  await evaluate("(()=>{window.__accountHoldAuth=true;const channel=new BroadcastChannel('aqua-session-events');channel.postMessage({type:'changed'});channel.close();return true})()");
  await waitFor("typeof window.__accountAuthRelease==='function'", 'real_same_owner_auth_read_held');
  await waitFor("Boolean(document.querySelector('.opal-workspace')?.closest('[hidden],[inert]'))&&!document.querySelector('.account-name-dialog[open]')", 'account_modal_hidden_during_auth_check');
  await check('Open account name modal leaves the native top layer while real auth authority is pending', "Boolean(document.querySelector('.opal-workspace')?.closest('[hidden],[inert]'))&&!document.querySelector('.account-name-dialog[open]')");
  await evaluate('window.__accountAuthRelease()');
  await waitFor("!document.querySelector('.opal-workspace')?.closest('[hidden],[inert]')&&Boolean(document.querySelector('.account-name-dialog[open]'))&&document.querySelector('[data-account-name-input]')?.disabled===false", 'account_modal_restored_after_confirmed_same_owner');
  await check('Confirmed same-owner auth restore retains the unsaved name draft', "document.querySelector('[data-account-name-input]').value==='Draft retained while checking sign-in'");
  const tab = async (shift = false) => {
    await ctx.cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, modifiers: shift ? 8 : 0 });
    await ctx.cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, modifiers: shift ? 8 : 0 });
  };
  await evaluate("document.querySelector('[data-account-save-name]').focus()"); await tab();
  await check('Native account modal wraps forward Tab to its name input', "document.activeElement===document.querySelector('[data-account-name-input]')");
  await tab(true);
  await check('Native account modal wraps reverse Tab to Save name', "document.activeElement===document.querySelector('[data-account-save-name]')");
  await ctx.cdp.send('Emulation.setDeviceMetricsOverride', { width: 320, height: 900, deviceScaleFactor: 1, mobile: false });
  await evaluate("document.documentElement.style.fontSize='200%'");
  await check('Account name modal reflows at 320px with doubled root text', "(()=>{const d=document.querySelector('.account-name-dialog[open]').getBoundingClientRect(),i=document.querySelector('[data-account-name-input]').getBoundingClientRect();return d.left>=0&&d.right<=innerWidth+1&&i.left>=0&&i.right<=innerWidth+1&&document.documentElement.scrollWidth<=innerWidth+1})()");
  await ctx.screenshot('p10a-account-mobile-name');
  await ctx.cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await ctx.cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await check('Escape closes the name modal and returns focus to Edit name', "!document.querySelector('.account-name-dialog[open]')&&document.activeElement===document.querySelector('[data-account-edit-name]')");
  await check('Account lists reflow at 320px with doubled root text', 'document.documentElement.scrollWidth<=innerWidth+1');
  await ctx.screenshot('p10a-account-mobile-settings');
  await evaluate("document.documentElement.style.fontSize=''");
  await ctx.cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await click('[data-settings-category="appearance"]');
  await evaluate('window.__accountHoldProfile=true');
  await click('[data-settings-category="account"]');
  await waitFor("typeof window.__accountRelease==='function'", 'real_profile_response_held');
  await click('[data-settings-category="appearance"]');
  await evaluate('window.__accountRelease()');
  await check('Leaving Account aborts that exact real held read and never publishes late identity', "window.__accountHeldEvent?.route==='/api/v1/me'&&window.__accountHeldEvent?.method==='GET'&&window.__accountHeldEvent?.aborted===true&&!document.querySelector('[data-account-foundation]')");
  await click('[data-settings-category="account"]');
  await waitFor("document.querySelector('[data-account-saved-name]')?.textContent==='Response reconciled name'", 'account_fresh_read_after_abort');
  await check('Remount reads current profile and leaves methods and sessions unloaded', "!document.querySelector('[data-account-methods]')&&!document.querySelector('[data-account-sessions]')");
  await ctx.screenshot('p10a-account-desktop');
  await clickText('Cancel changes', '.settings-savebar button');
  await check('Presentation Cancel does not undo the confirmed display name', "document.querySelector('[data-account-saved-name]')?.textContent==='Response reconciled name'&&(" + saveDisabled + ')');
  return { account_reads: await evaluate("window.__accountAudit.filter(e=>e.method==='GET').length"), account_write_attempts: await evaluate("window.__accountAudit.filter(e=>e.method==='PATCH').length"),
    fixture_dataset_grant: false, fake_jobs_requested: 0, actual_provider_calls: 0, observer: 'real_responses_only_with_explicit_hold_and_loss_cases' };
}
