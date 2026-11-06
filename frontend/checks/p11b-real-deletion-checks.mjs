import { accountAction } from './homepage-browser-actions.mjs';
import { googleCallback } from './p10c-identity-browser-checks.mjs';
import { assertShell } from './p05-shell-browser-checks.mjs';
const q = JSON.stringify;
const phase = value => `document.querySelector('[data-deletion-phase]')?.dataset.deletionPhase===${q(value)}`;
export const DELETION_SCRIPT = `(()=>{
 const perform=window.fetch.bind(window), secrets=[];let held=null,lose=false;
 window.__deletionAudit=[];
 window.__deletionBrowser={loseAccount(){lose=true;},clean(){const html=document.documentElement.outerHTML,storage=JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)]);return !location.hash&&secrets.every(value=>!html.includes(value)&&!storage.includes(value));},async staleWrite(){if(!held)throw Error('held_write_missing');const response=await perform('/api/v1/chats',held);await response.body?.cancel();return response.status;}};
 window.fetch=async(resource,options={})=>{
  const url=new URL(typeof resource==='string'?resource:resource.url,location.href),method=options.method||'GET';
  if(url.origin===location.origin&&url.pathname==='/api/v1/chats'&&method==='POST'&&!held){held={...options,headers:Object.fromEntries(new Headers(options.headers)),signal:undefined};const csrf=new Headers(options.headers).get('X-CSRF-Token');if(csrf)secrets.push(csrf);}
  let scope=null;if(url.pathname==='/api/v1/me/data-deletions'&&method==='POST'){const value=JSON.parse(options.body);scope=value.scope;secrets.push(value.receipt_token,value.proof_token);}
  const response=await perform(resource,options);
  if(url.pathname.startsWith('/api/v1/me/data-deletions')){if(window.__deletionAudit.length>=24)throw Error('deletion_audit_bound');window.__deletionAudit.push({route:url.pathname.replace(/by-intent\\/[a-f0-9-]+$/,'by-intent/:intent'),method,status:response.status});}
  if(scope==='account_v1'&&lose&&response.status===202){lose=false;await response.body?.cancel();throw new TypeError('Synthetic lost genuine account ACK');}
  return response;
 };
})();`;

export async function runRealDeletionChecks(ctx) {
  const { check, click, clickText, fill, waitFor, evaluate } = ctx;
  let firstVerifiedAt = 0;
  const purge = async states => {
    let result;
    for (let attempt = 0; attempt < 4; attempt++) {
      result = await ctx.bridge.send('deletion_purge');
      if (result.states.join() === states) return result;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    return result;
  };
  const submit = async question => {
    await fill('.opal-composer textarea', question); await click('[aria-label="Send message"]');
    await waitFor("Boolean(document.querySelector('.analysis-status[data-analysis-state=complete]'))&&!document.querySelector('[aria-label=\"Cancel analysis\"]')", 'deletion_synthetic_private_analysis_complete');
  };
  const review = async account => {
    await accountAction(ctx, 'Settings'); await click('[data-settings-category="privacy"]');
    await click(account ? '[data-delete-private-account]' : '[data-delete-private-history]');
    await waitFor(`${phase('review')}&&[...document.querySelectorAll('dialog button')].some(button=>button.textContent==='Continue to verification'&&!button.disabled)`, 'real_deletion_review');
    await clickText('Continue to verification', 'dialog button'); await waitFor(phase('verify'), 'real_deletion_verify');
    await click('[data-account-start-google]'); await googleCallback(ctx, 'owner'); await waitFor(phase('confirm'), 'real_deletion_proof');
    if (!account) firstVerifiedAt = performance.now();
    await fill('dialog input', account ? 'DELETE ACCOUNT' : 'DELETE HISTORY');
    if (account) await evaluate('window.__deletionBrowser.loseAccount();true');
    await click('[data-submit-private-deletion]'); await waitFor(phase('uncertain'), 'real_deletion_unconfirmed');
  };
  await ctx.navigate('/signin'); await googleCallback(ctx, 'owner');
  await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))&&!document.querySelector('.opal-composer textarea')?.disabled", 'real_deletion_owner_ready');
  await assertShell(check);
  const signed = JSON.parse((await ctx.rawRequest('GET', '/api/auth/me')).body);
  if (signed.can_query !== true) throw Error('real_deletion_initial_grant_missing');
  ctx.secrets.add(signed.csrf_token);
  await submit('P08 chart primitives');
  await fill('.opal-composer textarea', 'Synthetic unsaved draft before history retirement');
  await review(false);
  await check('Unpublished independent header cannot claim deletion acceptance', "!document.querySelector('[data-deletion-state]')&&window.__deletionAudit.filter(item=>item.route==='/api/v1/me/data-deletions').length===1");
  await click('[data-check-deletion-receipt]'); await waitFor("document.querySelector('[data-deletion-state]')?.dataset.deletionState==='awaiting_authority'", 'real_header_still_unpublished');
  let stats = await ctx.bridge.send('deletion_stats');
  if (stats.counts.chats !== 1 || stats.states.join() !== 'awaiting_authority' || stats.retained_signed_intents !== 0) throw Error('real_pending_header_purged_or_acknowledged');
  await ctx.bridge.send('deletion_publish');
  await click('[data-check-deletion-receipt]'); await waitFor("document.querySelector('[data-deletion-state]')?.dataset.deletionState==='accepted'", 'real_signed_header_accepted');
  stats = await purge('complete');
  if (stats.counts.chats !== 0 || stats.counts.messages !== 0 || stats.counts.analysis_jobs !== 0 || stats.retained_signed_intents !== 1 || stats.states.join() !== 'complete') throw Error('real_history_cleanup_incomplete');
  await click('[data-check-deletion-receipt]'); await waitFor("document.querySelector('[data-deletion-state]')?.dataset.deletionState==='complete'", 'real_history_cleanup_confirmed');
  await check('Actual history cleanup requires signed authority and completed bounded database purge', "window.__deletionAudit.filter(item=>item.route==='/api/v1/me/data-deletions').length===1&&window.__deletionBrowser.clean()");
  if (await evaluate('window.__deletionBrowser.staleWrite()') !== 409) throw Error('real_stale_history_write_not_fenced');
  await clickText('Close receipt', 'dialog button');
  await waitFor("[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='Back to workspace'&&button.getClientRects().length&&!button.closest('[hidden],[inert]'))", 'real_history_owner_refresh_finished');
  await clickText('Back to workspace');
  await waitFor("Boolean(document.querySelector('.opal-composer textarea'))", 'real_history_workspace_remounted');
  await check('History remount clears old results and unsaved drafts without resubmission', "document.querySelector('.opal-composer textarea').value===''&&!document.querySelector('.conversation .message--user,.financial-table,.visual-pane')");
  await submit('P08 text explanation');
  // Each deletion uses three real action admissions; the unchanged budget is
  // five per minute. Let its actual window expire before the second scope.
  const actionBudgetWait = Math.max(0, 61000 - (performance.now() - firstVerifiedAt));
  ctx.stage = 'real_account_action_window_cooldown';
  await new Promise(resolve => setTimeout(resolve, actionBudgetWait));
  await review(true);
  await check('Lost genuine account ACK clears private access while preserving an honest uncertain receipt', "!document.querySelector('.opal-workspace')&&!document.querySelector('[data-deletion-state]')&&window.__deletionBrowser.clean()");
  if ((await ctx.rawRequest('GET', '/api/auth/me')).status !== 401) throw Error('real_account_access_survived');
  await click('[data-check-deletion-receipt]'); await waitFor("document.querySelector('[data-deletion-state]')?.dataset.deletionState==='accepted'", 'real_account_receipt_after_revocation');
  stats = await purge('complete,complete');
  if (stats.states.join() !== 'complete,complete' || Object.values(stats.counts).some(value => value !== 0) || stats.retained_signed_intents !== 2 || stats.create_posts !== 2) throw Error('real_account_cleanup_incomplete');
  await click('[data-check-deletion-receipt]'); await waitFor("document.querySelector('[data-deletion-state]')?.dataset.deletionState==='complete'", 'real_account_live_cleanup_confirmed');
  await check('Purpose-only account receipt survives ordinary revocation without replaying its proof', "window.__deletionAudit.filter(item=>item.route==='/api/v1/me/data-deletions').length===2&&window.__deletionBrowser.clean()");
  await ctx.screenshot('p11b-actual-account-live-cleanup');
  await clickText('Close receipt', 'dialog button'); await googleCallback(ctx, 'owner');
  await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", 'real_account_fresh_uuid_login');
  const fresh = JSON.parse((await ctx.rawRequest('GET', '/api/auth/me')).body);
  if (fresh.user.id === signed.user.id || fresh.can_query !== false) throw Error('real_deleted_identity_reapproved');
  stats = await ctx.bridge.send('deletion_stats');
  if (!stats.new_uuid_relogin_denied || stats.relogin_grants !== 0 || stats.stale_write_denials !== 1 || stats.synthetic_authority !== false || stats.real_provider_calls !== 0) throw Error('real_authority_final_boundary_invalid');
  await check('A fresh account UUID cannot recover retired history or automatic legacy approval', "document.querySelector('.opal-composer textarea').disabled&&!document.querySelector('.conversation .message--user,.financial-table,.visual-pane')&&!document.querySelector('[data-deletion-phase]')");
  return { stats, actual_signed_authority: true, actual_app_routes: true, fake_pipeline_jobs: 2, action_budget_wait_ms: Math.ceil(actionBudgetWait), server_clock_or_limit_changes: 0, lost_response: 'genuine202_discarded_after_real_server_commit', automatic_create_replays: 0 };
}
