import assert from "node:assert/strict";
const q=JSON.stringify;
// This is deliberately part of the synthetic gate, after every prior journey.
// Its query/capability controls are contract doubles, never real dataset grants.
export async function runSyntheticNoticeChecks(ctx,{emailA,emailB}) {
  const {fixture,check,click,fill,waitFor,evaluate,navigate,signIn,viewport,screenshot}=ctx;
  await viewport(1440,900);fixture.email=null;fixture.canQuery=true;await navigate("/signin");await signIn(emailA);await navigate("/settings");
  await waitFor("document.querySelector('#settings-field-accent')?.disabled===false","notice_settings_ready");await click('[data-settings-category="notifications"]');
  await waitFor("document.querySelector('[data-notification-consent]')?.disabled===false","notice_consent_ready");
  await check("C optional success consent defaults off independently of presentation preferences","document.querySelector('[data-notification-consent]').checked===false&&!document.querySelector('.in-app-success-notice')");
  await click("[data-notification-consent]");await click("[data-save-notifications]");await waitFor("document.querySelector('[data-notification-settings]').textContent.includes('Notification settings saved.')","notice_explicit_server_consent_saved");
  await navigate("/");await waitFor("document.querySelector('.opal-composer textarea')?.disabled===false","notice_workspace_ready");
  const blank=async()=>{const button=await evaluate("Boolean([...document.querySelectorAll('[aria-label=\"New chat\"],.new-chat')].find(el=>el.getClientRects().length&&!el.closest('[hidden],[inert]')))");if(button)await click('[aria-label="New chat"],.new-chat');else assert.equal(await evaluate("!document.querySelector('.conversation .message--user')"),true);};
  await blank();const before=fixture.queryCount(),question="P07 synthetic private C notice fixture question";await fill(".opal-composer textarea",question);await click('[aria-label="Send message"]');await waitFor("document.querySelector('.analysis-status')?.dataset.analysisState==='queued'","notice_owned_live_job_queued");
  const requestId=[...fixture.analysisRequests.keys()].at(-1),entry=fixture.analysisRequests.get(requestId);assert.ok(entry&&entry.owner===emailA);
  const until=Date.now()+5500;while(entry.streams.size!==1&&Date.now()<until)await new Promise(resolve=>setTimeout(resolve,20));assert.equal(entry.streams.size,1);
  fixture.analysisChange(requestId,"running","generating");await waitFor("document.querySelector('.analysis-status')?.dataset.analysisState==='running'","notice_owned_live_job_running");
  await blank();fixture.analysisChange(requestId,"complete");await waitFor("document.querySelector('.in-app-success-notice p')?.textContent==='Your request is complete.'","notice_background_completion_visible");
  await check("C only an owned live background completion creates one fixed generic success message",`document.querySelectorAll('.in-app-success-notice').length===1&&!document.querySelector('.in-app-success-notices').textContent.includes(${q(question)})&&!/SELECT|synthetic completed answer/.test(document.querySelector('.in-app-success-notices').textContent)`);
  await screenshot("p10c-generic-live-success-notice");
  await evaluate("(()=>{const perform=window.fetch.bind(window);window.__cNoticeHoldAuth=true;window.fetch=(resource,options={})=>perform(resource,options).then(response=>{const url=new URL(typeof resource==='string'?resource:resource.url,location.href);if(url.origin===location.origin&&url.pathname==='/api/auth/me'&&window.__cNoticeHoldAuth){window.__cNoticeHoldAuth=false;return new Promise(resolve=>{window.__cNoticeReleaseAuth=()=>{delete window.__cNoticeReleaseAuth;resolve(response);};});}return response;});const c=new BroadcastChannel('aqua-session-events');c.postMessage({type:'changed'});c.close();return true})()");
  await waitFor("typeof window.__cNoticeReleaseAuth==='function'","notice_auth_read_held");
  await check("C pending real auth authority synchronously hides and clears optional queued notices","Boolean(document.querySelector('.opal-workspace[hidden][inert]'))&&!document.querySelector('.in-app-success-notices')");
  fixture.email=emailB;fixture.canQuery=false;await evaluate("(()=>{const c=new BroadcastChannel('aqua-session-events');c.postMessage({type:'changed'});c.close();return true})()");
  await waitFor("document.querySelector('.opal-account')?.textContent.includes('Fixture Reader B')&&!document.querySelector('.opal-workspace')?.closest('[hidden],[inert]')","notice_new_owner_confirmed");await evaluate("window.__cNoticeReleaseAuth()");
  await check("C a late old-owner auth read and permission loss cannot restore the previous notice queue","document.querySelector('.opal-account').textContent.includes('Fixture Reader B')&&document.querySelector('.opal-composer textarea').disabled&&!document.querySelector('.in-app-success-notices')");
  await navigate("/settings");await waitFor("document.querySelector('#settings-field-accent')?.disabled===false","notice_other_owner_settings_ready");await click('[data-settings-category="notifications"]');await waitFor("document.querySelector('[data-notification-consent]')?.disabled===false","notice_other_owner_consent_ready");
  await check("C another owner never inherits the prior owner's optional consent","document.querySelector('[data-notification-consent]').checked===false&&!document.querySelector('.in-app-success-notice')");
  fixture.email=emailA;fixture.canQuery=true;await navigate("/settings");await waitFor("document.querySelector('#settings-field-accent')?.disabled===false","notice_original_owner_restored");await click('[data-settings-category="notifications"]');await waitFor("document.querySelector('[data-notification-consent]')?.disabled===false","notice_original_consent_loaded");
  await check("C restoring confirmed consent does not replay historical completed requests","document.querySelector('[data-notification-consent]').checked===true&&!document.querySelector('.in-app-success-notice')");
  assert.equal(fixture.queryCount(),before+1);fixture.closeAnalysisStreams();
  return {mode:"synthetic_intercepted_api_real_production_dom",synthetic_analyses_requested:1,real_provider_calls:0,real_dataset_grants:0,auth_and_owner_privacy_checks:true};
}
