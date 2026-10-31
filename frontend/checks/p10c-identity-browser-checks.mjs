const q=JSON.stringify;
export const IDENTITY_SCENARIOS=new Set(["google-session","google-failure","link","unlink","password-add","email","lost-email","notifications","last-method"]);
export function identityStartsWithGoogle(scenario) {
  if(!IDENTITY_SCENARIOS.has(scenario))throw Error("identity_scenario_invalid");
  return ["google-session","google-failure","password-add","email","lost-email","last-method"].includes(scenario);
}
export const GOOGLE_FIXTURE_SCRIPT=`(()=>{let settings;window.__identityGoogle=null;window.google={accounts:{id:{initialize(value){settings=value;window.__identityGoogle=value;},disableAutoSelect(){},cancel(){},renderButton(node){const button=document.createElement('button');button.type='button';button.dataset.identityGoogleFixture='true';button.textContent='Continue with Google';button.onclick=()=>{const credential=window.__identityCredential;delete window.__identityCredential;settings.callback({credential});};node.replaceChildren(button);}}}};const perform=window.fetch.bind(window);window.__identityAudit=[];window.__identityMailRequest=null;window.__identityLoseReply=false;window.fetch=(resource,options={})=>{const url=new URL(typeof resource==='string'?resource:resource.url,location.href),method=(options.method||'GET').toUpperCase();if(url.origin===location.origin&&url.pathname.startsWith('/api/v1/me/')&&['POST','PUT'].includes(method))window.__identityAudit.push({route:url.pathname,method});return perform(resource,options).then(async response=>{if(url.origin===location.origin&&response.status===200&&['/api/v1/me/password-enrollments','/api/v1/me/email-change-requests'].includes(url.pathname)){const value=await response.clone().json();window.__identityMailRequest=value.request_id;}if(window.__identityLoseReply&&response.status===200&&url.pathname==='/api/v1/me/email'&&method==='PUT'){window.__identityLoseReply=false;throw new TypeError('Synthetic lost identity response');}return response;});};})();`;
export async function googleCallback(ctx,identity="owner",invalid=false) {
  await ctx.waitFor("Boolean(document.querySelector('[data-identity-google-fixture]'))&&Boolean(window.__identityGoogle?.nonce)","identity_google_control_ready");
  const issued=await ctx.evaluate("({nonce:window.__identityGoogle.nonce,client_id:window.__identityGoogle.client_id})");
  const value=invalid?{credential:"synthetic-invalid-google-credential"}:await ctx.bridge.send("google_assertion",{...issued,identity});
  if(!invalid&&(value.synthetic!==true||value.real_google_sdk_calls!==0))throw Error("identity_google_boundary_invalid");
  ctx.secrets.add(value.credential);
  await ctx.evaluate(`window.__identityCredential=${q(value.credential)};true`);await ctx.click("[data-identity-google-fixture]");
}
export async function assertIdentitySessionsEnded(ctx,originalToken) {
  if(await ctx.probeCopiedSession(originalToken)!==401)throw Error("identity_mutation_session_survived");
  // The copied-cookie probe is outside Chrome. Verify current browser access
  // separately so the fixture resumes from Chrome's actual login-cookie jar.
  if((await ctx.rawRequest("GET","/api/auth/me")).status!==401)throw Error("identity_current_browser_session_survived");
}
const phase=value=>`document.querySelector('[data-account-identity-phase]')?.dataset.accountIdentityPhase===${q(value)}`;
export async function verifyIdentityMethod(ctx,{scenario,password,privateMarkup}) {
  if(["password-add","email","lost-email"].includes(scenario)){
    await ctx.click("[data-account-start-google]");await googleCallback(ctx,"owner");
    await ctx.waitFor(phase("ready"),"identity_google_identity_proof_ready");
    await privateMarkup("Google assertion and action proof remain transient");
  }else{
    await ctx.fill("[data-account-current-password]",password);await privateMarkup("Current password never enters serialized markup or device storage");await ctx.click("[data-account-verify-password]");await ctx.waitFor(phase("ready"),"identity_current_password_verified");
  }
}
export async function signInAfterIdentityChange(ctx,{scenario,email,password,newPassword}) {
  if(scenario==="link")await googleCallback(ctx,"candidate");
  else if(["email","lost-email"].includes(scenario))await googleCallback(ctx,"owner");
  else{await ctx.fill("#auth-email",email);await ctx.fill("#auth-password",scenario==="password-add"?newPassword:password);await ctx.click('[data-testid=password-auth-submit]');}
}
export function assertIdentityResult({scenario,owner,email,signed,methods}) {
  if(signed.user.id!==owner||signed.can_query!==false)throw Error("identity_account_continuity_invalid");
  if(scenario==="password-add"&&methods.password.linked!==true||scenario==="link"&&methods.google.linked!==true||scenario==="unlink"&&methods.google.linked!==false)throw Error("identity_final_method_invalid");
  if(["email","lost-email"].includes(scenario)&&(signed.user.email!=="p10c-new-reader@example.test"||methods.password.linked!==false||methods.google.linked!==true||methods.google.identities.length!==1||methods.google.identities[0].email!==email))throw Error("identity_email_provider_continuity_invalid");
}
export function lostEmailReviewReady(state) {
  const writes=[["/api/v1/me/reauth/google-challenges","POST"],["/api/v1/me/reauth/google","POST"],["/api/v1/me/email-change-requests","POST"],["/api/v1/me/email","PUT"]];
  return state?.phase==="uncertain"&&state.confirmAbsent===true&&state.startAbsent===true&&state.verifyAbsent===true&&state.reviewEnabled===true&&state.alert==="AQUA could not confirm whether the change finished. Check current access before starting a new action."&&Array.isArray(state.audit)&&state.audit.length===writes.length&&state.audit.every((item,index)=>item.route===writes[index][0]&&item.method===writes[index][1]);
}
export async function runIdentityChecks(ctx,{scenario,email,password,newPassword}) {
  if(!IDENTITY_SCENARIOS.has(scenario)||ctx.accountIdentityFixture!==true)throw Error("identity_fixture_required");
  const {check,click,fill,waitFor,evaluate}=ctx;
  const me=JSON.parse((await ctx.rawRequest("GET","/api/auth/me")).body),owner=me.user.id;
  if(me.can_query!==false)throw Error("identity_grant_boundary_invalid");
  const cookies=(await ctx.cdp.send("Network.getCookies",{urls:[ctx.origin]})).cookies,original=cookies.find(cookie=>cookie.name==="__Host-aqua_session");
  if(!original?.secure||!original.httpOnly||original.domain!=="aqua-browser.example.test"||original.path!=="/")throw Error("identity_session_cookie_invalid");ctx.secrets.add(original.value);
  await ctx.navigate("/settings");await waitFor("document.querySelector('#settings-field-accent')?.disabled===false","identity_settings_ready");
  if(scenario==="notifications"){
    await click('[data-settings-category="notifications"]');await waitFor("document.querySelector('[data-notification-consent]')?.disabled===false","identity_notifications_ready");
    await check("Real notification consent starts off separately from presentation preferences","!document.querySelector('[data-notification-consent]').checked");
    await click("[data-notification-consent]");await check("Editing optional consent performs no server mutation","window.__identityAudit.length===0");await click("[data-save-notifications]");
    await waitFor("document.querySelector('[data-notification-settings]').textContent.includes('Notification settings saved.')","identity_notifications_saved");
    const saved=JSON.parse((await ctx.rawRequest("GET","/api/v1/me/notification-settings")).body);if(saved.user_id!==owner||saved.values.in_app_success!==true)throw Error("identity_notifications_save_invalid");
    const auth=JSON.parse((await ctx.rawRequest("GET","/api/auth/me")).body);ctx.secrets.add(auth.csrf_token);
    const conflict=await ctx.rawRequest("PUT","/api/v1/me/notification-settings",{expectedRevision:saved.revision-1,in_app_success:false,preview:"hidden"},auth.csrf_token);if(conflict.status!==409)throw Error("identity_notifications_cas_invalid");
    await ctx.navigate("/settings");await waitFor("document.querySelector('#settings-field-accent')?.disabled===false","identity_saved_settings_ready");await click('[data-settings-category="notifications"]');await waitFor("document.querySelector('[data-notification-consent]')?.checked===true","identity_saved_consent_reloaded");
    await check("Persisted consent survives reload and a stale CAS cannot overwrite it","document.querySelector('[data-notification-consent]').checked&&!document.querySelector('.in-app-success-notice')");await ctx.screenshot("p10c-notifications-saved");
    return {scenario,post_put_attempts:2,real_google_sdk_calls:0,real_mail_provider_calls:0,fake_jobs_requested:0,fixture_dataset_grant:false};
  }
  await click('[data-settings-category="account"]');await waitFor("Boolean(document.querySelector('[data-account-profile]'))","identity_profile_ready");await click("[data-account-load-methods]");await waitFor("Boolean(document.querySelector('[data-account-methods]'))","identity_methods_ready");
  if(scenario==="last-method"){
    await check("The only usable Google method cannot be removed","document.querySelector('[data-account-unlink-google]')?.disabled===true&&document.querySelector('[data-account-add-password]')?.disabled===false&&window.__identityAudit.length===0");await ctx.screenshot("p10c-last-method-preserved");return {scenario,post_put_attempts:0,real_google_sdk_calls:0,real_mail_provider_calls:0,fake_jobs_requested:0,fixture_dataset_grant:false};
  }
  const verifyPassword=()=>verifyIdentityMethod(ctx,{scenario:"unlink",password,privateMarkup});
  const privateMarkup=label=>check(label,`(()=>{const html=document.documentElement.outerHTML,storage=JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)]);return !location.hash&&${q([...ctx.secrets])}.every(value=>!html.includes(value)&&!storage.includes(value))})()`);
  const googleProof=async(invalid=false)=>{await click("[data-account-start-google]");await googleCallback(ctx,"owner",invalid);};
  if(["google-session","google-failure"].includes(scenario)){
    await click("[data-account-load-sessions]");await waitFor("Boolean(document.querySelector('[data-account-revoke-session=current]'))","identity_google_session_ready");await click("[data-account-revoke-session=current]");
    await googleProof(scenario==="google-failure");
    if(scenario==="google-failure"){
      await waitFor("document.querySelector('[data-account-security-phase]')?.dataset.accountSecurityPhase==='verify'&&Boolean(document.querySelector('.account-security-dialog [role=alert]'))","identity_google_invalid_rejected");await check("Unverified Google assertion cannot expose final confirmation or end current access","!document.querySelector('[data-account-confirm-security]')&&window.__identityAudit.length===2");if((await ctx.rawRequest("GET","/api/auth/me")).status!==200)throw Error("identity_failed_proof_ended_session");
    }else{
      await waitFor("document.querySelector('[data-account-security-phase]')?.dataset.accountSecurityPhase==='confirm'","identity_google_session_proof_ready");await check("Google action proof requires separate confirmation with Cancel focused","document.activeElement?.textContent==='Cancel'&&window.__identityAudit.length===2");await privateMarkup("Google assertion and action proof remain transient");await click("[data-account-confirm-security]");await waitFor("document.querySelector('#auth-password')?.disabled===false","identity_google_session_ended");if(await ctx.probeCopiedSession(original.value)!==401)throw Error("identity_google_session_revoke_invalid");
    }
    await ctx.screenshot("p10c-"+scenario+"-result");return {scenario,post_put_attempts:scenario==="google-session"?3:2,real_google_sdk_calls:0,real_mail_provider_calls:0,fake_jobs_requested:0,fixture_dataset_grant:false};
  }
  const launch=scenario==="password-add"?"[data-account-add-password]":["email","lost-email"].includes(scenario)?"[data-account-change-email]":"[data-account-link-google]";
  await click(launch);await waitFor("Boolean(document.querySelector('.account-identity-dialog[open]'))","identity_dialog_open");await check("Identity action starts with Cancel focused and no mutation","document.activeElement?.textContent==='Cancel'&&window.__identityAudit.length===0");
  if(["email","lost-email"].includes(scenario)){await fill('.account-identity-dialog input[type=email]',"p10c-new-reader@example.test");await clickText(ctx,"Continue to verification");}
  await verifyIdentityMethod(ctx,{scenario,password,privateMarkup});
  await click("[data-account-start-identity]");
  if(["link","unlink"].includes(scenario)){
    await googleCallback(ctx,"candidate");await waitFor(phase("candidate"),"identity_candidate_ready");await check("Candidate is reviewed separately and does not replace the app primary email",`document.querySelector('.account-identity-dialog').textContent.includes('candidate.identity@example.test')&&document.querySelector('[data-account-primary-email]').textContent===${q(email)}&&window.__identityAudit.length===4`);
  }else{
    await waitFor(phase("mail")+"&&Boolean(window.__identityMailRequest)","identity_mail_requested");
    const request_id=await evaluate("window.__identityMailRequest"),purposes=scenario==="password-add"?["password_add"]:["email_change_new","email_change_old"];
    const all=(await ctx.cdp.send("Network.getCookies",{urls:[ctx.origin]})).cookies;
    for(const name of ["__Host-aqua_account_action","__Host-aqua_identity_action"]){const value=all.find(cookie=>cookie.name===name);if(!value?.secure||!value.httpOnly||value.path!=="/"||value.sameSite!=="Lax")throw Error("identity_binding_cookie_invalid");ctx.secrets.add(value.value);}
    for(const purpose of purposes){const mail=await ctx.bridge.send("identity_mailbox",{purpose,request_id});if(!mail.found||mail.body_exposed!==false||typeof mail.link!=="string")throw Error("identity_mail_not_available");ctx.secrets.add(mail.proof);ctx.secrets.add(mail.link);await fill(`[data-account-mail-link=${purpose}]`,mail.link);await privateMarkup("Pasted mailbox link remains absent from URL, markup and storage");await ctx.clickText("Use this confirmation link",`.account-identity-dialog label:has([data-account-mail-link=${purpose}]) button`);await check("Accepted mailbox input is immediately cleared",`document.querySelector('[data-account-mail-link=${purpose}]').value===''`);}
    await waitFor(phase("mail-confirm"),"identity_mail_confirm_ready");if(scenario==="password-add"){await fill('.account-identity-dialog input[autocomplete="new-password"]',newPassword);await fill('.account-identity-dialog label:has(input[autocomplete="new-password"]):last-of-type input',newPassword);ctx.secrets.add(newPassword);}
  }
  await privateMarkup("Identity proof and mailbox/candidate bearers remain transient before final confirmation");
  await ctx.cdp.send("Emulation.setDeviceMetricsOverride",{width:320,height:900,deviceScaleFactor:1,mobile:false});await evaluate("document.documentElement.style.fontSize='200%'");
  await check("Identity confirmation reflows at320px and200percent text without horizontal clipping","(()=>{const d=document.querySelector('.account-identity-dialog[open]').getBoundingClientRect();return d.left>=0&&d.right<=innerWidth+1&&document.documentElement.scrollWidth<=innerWidth+1;})()");await ctx.screenshot("p10c-"+scenario+"-mobile-confirm");await evaluate("document.documentElement.style.fontSize=''");await ctx.cdp.send("Emulation.setDeviceMetricsOverride",{width:1440,height:900,deviceScaleFactor:1,mobile:false});await ctx.screenshot("p10c-"+scenario+"-confirm");
  if(scenario==="lost-email")await evaluate("window.__identityLoseReply=true");
  await click("[data-account-confirm-identity]");
  if(scenario==="lost-email"){await waitFor(phase("uncertain"),"identity_lost_reply_uncertain");await check("Lost email completion cannot claim success or replay its mutation",`(${lostEmailReviewReady.toString()})((()=>{const dialog=document.querySelector('.account-identity-dialog'),review=[...dialog.querySelectorAll('button')].find(item=>item.textContent==='Check current access');return {phase:dialog.querySelector('[data-account-identity-phase]')?.dataset.accountIdentityPhase,confirmAbsent:!document.querySelector('[data-account-confirm-identity]'),startAbsent:!document.querySelector('[data-account-start-identity]'),verifyAbsent:!document.querySelector('[data-account-verify-password],[data-account-start-google]'),reviewEnabled:Boolean(review&&!review.disabled&&review.getClientRects().length&&!review.closest('[hidden],[inert]')),alert:dialog.querySelector('[role=alert]')?.textContent,audit:window.__identityAudit};})())`);await ctx.screenshot("p10c-lost-email-uncertain");await ctx.clickText("Check current access",".account-identity-dialog button");}
  await waitFor("document.querySelector('#auth-password')?.disabled===false","identity_current_sessions_ended");await assertIdentitySessionsEnded(ctx,original.value);
  if(scenario==="lost-email")await check("Access reconciliation cannot replay the lost email mutation","window.__identityAudit.length===4");
  const notices=await ctx.bridge.send("identity_mail_status"),purpose=["link","unlink"].includes(scenario)?"google_linked":scenario==="password-add"?"password_added":"email_changed",notice=notices.purposes?.[purpose];if(notices.body_exposed!==false||notices.real_provider_calls!==0||!notice||notice.failed!==0||notice.queued+notice.completed<(["email","lost-email"].includes(scenario)?2:1))throw Error("identity_notice_boundary_invalid");
  ctx.results.push({check:"Mandatory encrypted security notices remain obligated independently of optional consent",passed:true});
  if(scenario==="unlink"){
    // The preceding link used the unchanged five-action budget. Wait for the
    // real account cooldown, without changing rows, clocks or policy.
    await new Promise(resolve=>setTimeout(resolve,61000));await fill("#auth-email",email);await fill("#auth-password",password);await click('[data-testid=password-auth-submit]');await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))","identity_relinked_owner_signed_in");await ctx.navigate("/settings");await waitFor("document.querySelector('#settings-field-accent')?.disabled===false","identity_unlink_settings_ready");await click('[data-settings-category="account"]');await waitFor("Boolean(document.querySelector('[data-account-profile]'))","identity_unlink_profile_ready");await click("[data-account-load-methods]");await waitFor("document.querySelector('[data-account-unlink-google]')?.disabled===false","identity_unlink_method_ready");await click("[data-account-unlink-google]");await verifyPassword();await click("[data-account-confirm-identity]");await waitFor("document.querySelector('#auth-password')?.disabled===false","identity_unlink_complete");
  }
  await signInAfterIdentityChange(ctx,{scenario,email,password,newPassword});
  await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))","identity_confirmed_method_signed_in");
  const signed=JSON.parse((await ctx.rawRequest("GET","/api/auth/me")).body);
  const methods=JSON.parse((await ctx.rawRequest("GET","/api/v1/me/methods")).body);
  assertIdentityResult({scenario,owner,email,signed,methods});
  if(["email","lost-email"].includes(scenario))ctx.results.push({check:"Changed AQUA primary email preserves the same Google identity with its unchanged provider email",passed:true});
  ctx.results.push({check:"Ordinary sign-in confirms the same canonical owner and exact resulting method without analytical access",passed:true});
  await ctx.screenshot("p10c-"+scenario+"-result");
  return {scenario,post_put_attempts:scenario==="unlink"?8:["link"].includes(scenario)?5:4,real_google_sdk_calls:0,real_mail_provider_calls:0,fake_jobs_requested:0,fixture_dataset_grant:false,server_quota_clock_or_limit_changes:0,genuine_cooldown_wait_seconds:scenario==="unlink"?61:0};
}
const clickText=(ctx,text)=>ctx.clickText(text,".account-identity-dialog button");
