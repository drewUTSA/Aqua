import { exportScenario, expectedExportActions, EXPORT_FILE, EXPORT_MARKER } from './p11a-export-browser-contract.mjs';
import { googleCallback } from './p10c-identity-browser-checks.mjs';
import { SECURE_ACCOUNT_ORIGIN } from './p10b-browser-mode.mjs';
const q = JSON.stringify;
const phase = value => `document.querySelector('[data-export-dialog-phase]')?.dataset.exportDialogPhase===${q(value)}`;

// Only the two labeled transport-fault journeys change response bytes. All
// requests still reach the real private API. Saving is always intercepted so
// no browser journey writes an OS download or exposes private JSON in a report.
export const EXPORT_FIXTURE_SCRIPT = String.raw`(()=>{
 if(globalThis.location?.origin!==${q(SECURE_ACCOUNT_ORIGIN)})return;
 if(globalThis.isSecureContext!==true||typeof globalThis.crypto?.subtle?.digest!=='function'||typeof globalThis.fetch!=='function'||typeof globalThis.URL!=='function'||typeof globalThis.URL.createObjectURL!=='function'||typeof globalThis.URL.revokeObjectURL!=='function'||typeof globalThis.HTMLAnchorElement?.prototype?.click!=='function')throw Error('export_fixture_secure_context_required');
 const perform=window.fetch.bind(window),digest=crypto.subtle.digest.bind(crypto.subtle),create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL),click=HTMLAnchorElement.prototype.click;
 const blobs=new Map();window.__exportAudit=[];window.__exportJob=null;window.__exportLost=false;window.__exportFault=null;window.__exportHoldHash=false;
 window.__exportMetrics={created:0,revoked:0,offered:0,transport_faults:0};
 URL.createObjectURL=value=>{const url=create(value);if(value instanceof Blob&&value.type==='application/json'){blobs.set(url,value);window.__exportMetrics.created++;}return url;};
 URL.revokeObjectURL=url=>{if(blobs.delete(url))window.__exportMetrics.revoked++;return revoke(url);};
 HTMLAnchorElement.prototype.click=function(){if(this.download||this.href.startsWith('blob:')){if(this.download!==${q(EXPORT_FILE)}||!this.href.startsWith('blob:')||!blobs.has(this.href))throw Error('unknown_export_blob');window.__exportMetrics.offered++;return;}return click.call(this);};
 window.__exportInspect=async(marker,secrets)=>{if(blobs.size!==1)return false;const blob=[...blobs.values()][0],bytes=new Uint8Array(await blob.arrayBuffer());try{const text=new TextDecoder().decode(bytes),sha=Array.from(new Uint8Array(await digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');return blob.type==='application/json'&&bytes.length===window.__exportJob.byte_count&&sha===window.__exportJob.sha256&&text.includes(marker)&&secrets.every(secret=>!text.includes(secret));}finally{bytes.fill(0);}};
 crypto.subtle.digest=async(algorithm,value)=>{const result=await digest(algorithm,value);if(window.__exportHoldHash&&(algorithm==='SHA-256'||algorithm?.name==='SHA-256')){window.__exportHoldHash=false;window.__exportHeldBytes=new Uint8Array(value.buffer||value,value.byteOffset||0,value.byteLength);await new Promise(resolve=>window.__exportReleaseHash=()=>{delete window.__exportReleaseHash;resolve();});}return result;};
 window.fetch=async(resource,options={})=>{const url=new URL(typeof resource==='string'?resource:resource.url,location.href),method=(options.method||'GET').toUpperCase(),relevant=url.origin===location.origin&&/^\/api\/v1\/me\/(?:data-exports|reauth)/.test(url.pathname);
  if(relevant){if(window.__exportAudit.length>=128)throw Error('export_audit_bound');window.__exportAudit.push({path:url.pathname,method});}
  const response=await perform(resource,options);
  if(url.origin===location.origin&&/^\/api\/v1\/me\/data-exports(?:\/by-intent\/[^/]+|\/[^/]+)?$/.test(url.pathname)&&[200,202].includes(response.status)){const value=await response.clone().json();if(value.job)window.__exportJob=value.job;
   if(window.__exportLost&&method==='POST'&&url.pathname==='/api/v1/me/data-exports'){window.__exportLost=false;await response.body?.cancel();throw new TypeError('Synthetic lost export response');}}
  if(url.origin===location.origin&&/^\/api\/v1\/me\/data-exports\/[^/]+\/download$/.test(url.pathname)&&response.status===200&&window.__exportFault){const fault=window.__exportFault;window.__exportFault=null;const bytes=new Uint8Array(await response.arrayBuffer());try{if(!bytes.length||bytes.length>16384)throw Error('export_fault_body_bound');if(fault==='digest-mismatch')bytes[0]^=1;else if(fault!=='partial-download')throw Error('export_fault_invalid');const body=fault==='partial-download'?bytes.subarray(0,bytes.length-1):bytes;window.__exportMetrics.transport_faults++;return new Response(body,{status:200,headers:response.headers});}finally{bytes.fill(0);}}
  return response;};
 window.__exportBlobCount=()=>blobs.size;
})();`;

export async function runExportChecks(ctx, { scenario, password }) {
  exportScenario(scenario);
  if (ctx.personalExportFixture !== true || ctx.accountIdentityFixture !== true) throw Error('personal_export_fixture_required');
  const { click, clickText, fill, waitFor, check, evaluate } = ctx;
  const meResponse = await ctx.rawRequest('GET', '/api/auth/me');
  const me = JSON.parse(meResponse.body);
  if (meResponse.status !== 200 || me.can_query !== false) throw Error('export_owner_authority_invalid');
  ctx.secrets.add(me.csrf_token);
  const cookies = (await ctx.cdp.send('Network.getCookies', { urls: [ctx.origin] })).cookies;
  const cookie = cookies.find(item => item.name === '__Host-aqua_session');
  if (!cookie?.secure || !cookie.httpOnly || cookie.path !== '/' || cookie.sameSite !== 'Lax' || cookie.domain !== 'aqua-browser.example.test') throw Error('export_session_cookie_invalid');
  ctx.secrets.add(cookie.value);
  const project = await ctx.rawRequest('POST', '/api/v1/projects', { client_request_id: await evaluate('crypto.randomUUID()'), name: EXPORT_MARKER }, me.csrf_token);
  if (![200, 201].includes(project.status)) throw Error('export_owned_project_setup_failed');
  await ctx.navigate('/settings');
  await waitFor("document.querySelector('#settings-field-accent')?.disabled===false", 'export_settings_ready');
  await click('[data-settings-category="privacy"]');
  await waitFor("document.querySelector('[data-start-private-export]')?.disabled===false", 'export_capability_ready');
  await check('Personal exports require the explicit server capability and make no eager job-history read', "window.__exportAudit.length===0&&Boolean(document.querySelector('[data-review-private-exports]'))&&!document.querySelector('[data-save-private-export]')");
  const markup = label => check(label, `(()=>{const html=document.documentElement.outerHTML,storage=JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)]);return !location.hash&&${q([...ctx.secrets])}.every(value=>!html.includes(value)&&!storage.includes(value));})()`);
  const openReview = async () => {
    await click('[data-start-private-export]');
    await waitFor(phase('review'), 'export_scope_review_ready');
  };
  await openReview();
  await check('The scope review focuses Cancel and queues nothing before fresh verification', "document.activeElement?.textContent==='Cancel'&&window.__exportAudit.every(item=>item.method==='GET')&&!document.querySelector('[data-create-private-export]')");
  await clickText('Cancel', '.data-export-dialog button');
  await check('Cancel before verification leaves no export mutation or background job', "!document.querySelector('.data-export-dialog[open]')&&window.__exportAudit.every(item=>item.method==='GET')");
  await openReview();
  await clickText('Continue to verification', '.data-export-dialog button');
  await waitFor(phase('verify'), 'export_verification_ready');
  if (scenario === 'google-export') {
    await click('[data-account-start-google]');
    await googleCallback(ctx, 'owner');
  } else {
    await fill('[data-account-current-password]', scenario === 'verification-failure' ? 'Synthetic incorrect export password' : password);
    await markup('Entered password stays absent from markup, URLs and persistent browser stores');
    await click('[data-account-verify-password]');
  }
  if (scenario === 'verification-failure') {
    await waitFor(phase('verify') + "&&Boolean(document.querySelector('.data-export-dialog [role=alert]'))", 'export_bad_password_rejected');
    await check('Failed real verification clears the secret and cannot expose export confirmation', "document.querySelector('[data-account-current-password]').value===''&&!document.querySelector('[data-create-private-export]')&&!window.__exportAudit.some(item=>item.method==='POST'&&item.path==='/api/v1/me/data-exports')");
    await markup('Failed proof cannot place a bearer in markup or persistent storage');
    await ctx.screenshot('p11a-verification-failure');
    return expectedExportActions(scenario);
  }
  await waitFor(phase('confirm'), 'export_fresh_proof_ready');
  await check('Fresh proof requires a separate Create export click with Cancel initially focused', "document.activeElement?.textContent==='Cancel'&&window.__exportAudit.filter(item=>item.method==='POST').length===2");
  await markup('Action proof and current credentials remain transient before export creation');
  await ctx.cdp.send('Emulation.setDeviceMetricsOverride', { width: 320, height: 900, deviceScaleFactor: 1, mobile: false });
  await evaluate("document.documentElement.style.fontSize='200%'");
  await check('Export confirmation reflows at 320px and doubled text without horizontal clipping', "(()=>{const d=document.querySelector('.data-export-dialog[open]').getBoundingClientRect();return d.left>=0&&d.right<=innerWidth+1&&document.documentElement.scrollWidth<=innerWidth+1;})()");
  await ctx.screenshot('p11a-' + scenario + '-mobile-confirm');
  await evaluate("document.documentElement.style.fontSize=''");
  await ctx.cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  if (scenario === 'lost-create') await evaluate('window.__exportLost=true');
  await click('[data-create-private-export]');
  if (scenario === 'lost-create') {
    await waitFor(phase('uncertain'), 'export_lost_creation_uncertain');
    await check('A lost POST reply cannot claim success, reuse proof or replay creation automatically', "!document.querySelector('[data-create-private-export]')&&window.__exportAudit.filter(item=>item.method==='POST'&&item.path==='/api/v1/me/data-exports').length===1");
    await ctx.screenshot('p11a-lost-create-uncertain');
    await click('[data-check-export-intent]');
  }
  await waitFor("Boolean(document.querySelector('[data-export-job-state]'))&&!document.querySelector('.data-export-dialog[open]')", 'export_job_observed');
  await check('An accepted queued or working job is distinct from a downloadable ready file', "!document.querySelector('[data-save-private-export]')&&['queued','working','ready'].includes(document.querySelector('[data-export-job-state]').dataset.exportJobState)");
  await waitFor("document.querySelector('[data-download-private-export]')?.disabled===false", 'export_real_worker_ready', 30000);
  const job = await evaluate('window.__exportJob');
  if (!job || job.state !== 'ready' || !Number.isSafeInteger(job.byte_count) || job.byte_count < 1 || job.byte_count > 16384) throw Error('export_small_real_fixture_required');
  await check('Readiness has a real one-hour server expiry and no raw JSON preview', "(()=>{const j=window.__exportJob,p=document.querySelector('[data-private-exports]');return Date.parse(j.expires_at)-Date.parse(j.created_at)===3600000&&!p.textContent.includes('schemaVersion')&&!p.querySelector('pre,textarea');})()");
  await click('[data-review-private-exports]');
  await waitFor("document.querySelectorAll('.export-job-list li').length===1", 'export_explicit_retained_review');
  await check('Explicit review returns only the owned retained job and does not create another export', "window.__exportAudit.filter(item=>item.path==='/api/v1/me/data-exports'&&item.method==='POST').length===1&&document.querySelectorAll('.export-job-list li').length===1");
  if (scenario === 'foreign-probes') {
    const missingCsrf = await ctx.rawRequest('GET', '/api/v1/me/data-exports/' + job.id + '/download');
    if (missingCsrf.status !== 403) throw Error('export_download_missing_csrf_not_denied');
    if ((await ctx.rawRequest('POST', '/api/auth/logout', null, me.csrf_token)).status !== 204) throw Error('export_owner_logout_failed');
    await ctx.navigate('/signin'); await googleCallback(ctx, 'candidate');
    await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", 'export_distinct_candidate_ready');
    const foreign = JSON.parse((await ctx.rawRequest('GET', '/api/auth/me')).body);ctx.secrets.add(foreign.csrf_token);
    if (foreign.user.id === me.user.id || foreign.can_query !== false) throw Error('export_distinct_owner_required');
    for (const path of ['/api/v1/me/data-exports/' + job.id, '/api/v1/me/data-exports/by-intent/' + job.intent_id, '/api/v1/me/data-exports/' + job.id + '/download']) {
      if ((await ctx.rawRequest('GET', path, null, foreign.csrf_token)).status !== 404) throw Error('export_foreign_job_not_hidden');
    }
    await ctx.navigate('/settings');await waitFor("document.querySelector('#settings-field-accent')?.disabled===false", 'export_foreign_settings_ready');await click('[data-settings-category="privacy"]');await click('[data-review-private-exports]');
    await waitFor("document.querySelector('[data-private-exports]').textContent.includes('No retained exports are available.')", 'export_foreign_review_empty');
    await check('A distinct real owner sees generic404 for the original job, intent and paired-CSRF download', "!document.querySelector('[data-export-job-state]')&&!document.querySelector('[data-save-private-export]')&&window.__exportMetrics.offered===0");
    await ctx.screenshot('p11a-foreign-owner-empty');
    return expectedExportActions(scenario);
  }
  if (scenario === 'hash-interruption') await evaluate('window.__exportHoldHash=true');
  if (['partial-download', 'digest-mismatch'].includes(scenario)) await evaluate('window.__exportFault=' + q(scenario));
  await click('[data-download-private-export]');
  if (scenario === 'hash-interruption') {
    await waitFor("typeof window.__exportReleaseHash==='function'", 'export_native_hash_held');
    if ((await ctx.rawRequest('POST', '/api/auth/logout', null, me.csrf_token)).status !== 204) throw Error('export_hash_logout_failed');
    await evaluate("(()=>{const channel=new BroadcastChannel('aqua-session-events');channel.postMessage({type:'changed'});channel.close();return true;})()");
    await waitFor("Boolean(document.querySelector('#auth-password'))", 'export_hash_auth_ended');
    await evaluate('window.__exportReleaseHash()');
    await waitFor('window.__exportHeldBytes.every(value=>value===0)', 'export_late_hash_bytes_wiped');
    await check('Actual sign-out during hashing wipes private bytes and prevents late Blob publication', "window.__exportMetrics.created===0&&window.__exportMetrics.offered===0&&window.__exportBlobCount()===0&&!document.querySelector('[data-save-private-export]')");
    await evaluate('window.__exportHeldBytes=null');
    await ctx.screenshot('p11a-hash-authority-ended');
    return expectedExportActions(scenario);
  }
  if (['partial-download', 'digest-mismatch'].includes(scenario)) {
    await waitFor("Boolean(document.querySelector('[data-private-exports] [role=alert]'))", 'export_local_transport_fault_rejected');
    await check('A labeled local partial or digest fault cannot offer any unverified private file', "window.__exportMetrics.transport_faults===1&&window.__exportMetrics.created===0&&window.__exportMetrics.offered===0&&!document.querySelector('[data-save-private-export]')");
    await ctx.screenshot('p11a-' + scenario + '-rejected');
    return expectedExportActions(scenario);
  }
  await waitFor("document.querySelector('[data-save-private-export]')?.disabled===false", 'export_verified_file_prepared');
  await check('Only exact real export bytes and SHA produce an ephemeral fixed-name Blob', `window.__exportInspect(${q(EXPORT_MARKER)},${q([password, ...ctx.secrets].filter(value => typeof value === 'string' && value.length > 10))})`);
  await markup('Prepared private content is absent from markup, URLs and persistent browser stores');
  await ctx.screenshot('p11a-' + scenario + '-prepared');
  await click('[data-save-private-export]');
  await check('Save requests one browser download and immediately revokes its Blob without claiming an OS save', "window.__exportMetrics.offered===1&&window.__exportMetrics.revoked===1&&window.__exportBlobCount()===0&&document.querySelector('[data-private-exports]').textContent.includes('Download requested. Your browser controls whether and where the file is saved.')");
  await ctx.screenshot('p11a-' + scenario + '-requested');
  return expectedExportActions(scenario);
}
