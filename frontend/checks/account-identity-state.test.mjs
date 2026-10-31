import assert from "node:assert/strict";
import test from "node:test";
import { createIdentityIntentVault,identityFlowReducer,identityFlowState } from "../src/settings/accountIdentityState.js";
import { parseAccountMailLink } from "../src/settings/accountMailHandoff.js";
import { notificationEditor,notificationReducer,createLiveNoticeGate } from "../src/settings/notificationState.js";
import { actionKey,canAccountAction } from "../src/settings/accountSecurityState.js";
import { consumeLocation } from "../src/services/routes.js";
import { createGoogleCallbackGate } from "../src/settings/googleActionState.js";
import { createAccountRequestScope } from "../src/settings/accountState.js";
import { assertIdentitySessionsEnded,googleCallback,identityStartsWithGoogle,verifyIdentityMethod,signInAfterIdentityChange,assertIdentityResult,lostEmailReviewReady } from "./p10c-identity-browser-checks.mjs";
const ID="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",OTHER="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",TOKEN="v2."+"a".repeat(43),CODE="b".repeat(43),ORIGIN="https://aqua-browser.example.test";
const values=(enabled=false,preview="generic")=>({in_app_success:enabled,preview});
const snapshot=(revision=1,enabled=false)=>({user_id:ID,revision,values:values(enabled),capabilities:{in_app:true}});
test("confirmation links bind exact origin, purpose and public request without a fetch",t=>{
 const fetch=t.mock.method(globalThis,"fetch",()=>{throw Error("network forbidden");}),options={origin:ORIGIN,purpose:"password_add",requestId:ID},url=ORIGIN+"/account-action/password_add#request="+ID+"&token="+CODE;
 assert.equal(parseAccountMailLink(url,options),CODE);
 for(const bad of [url.replace(ORIGIN,"https://foreign.example.test"),url.replace("password_add","email_change_new"),url.replace(ID,OTHER),url+"&token="+CODE,url.replace("#request","?x=1#request"),url.replace(CODE,"short"),CODE,url+"\n"])assert.throws(()=>parseAccountMailLink(bad,options));assert.equal(fetch.mock.calls.length,0);
});
test("mail landing strips bearer before returning any route data",()=>{
 const calls=[],result=consumeLocation({pathname:"/account-action/email_change_new",hash:"#request="+ID+"&token="+CODE,search:""},{replaceState(...args){calls.push(args);}});
 assert.equal(result.path,"/account-action/email_change_new");assert.equal(result.proof,null);assert.deepEqual(calls,[[null,"","/account-action/email_change_new"]]);assert.ok(!JSON.stringify(result).includes(CODE));
});
test("mail intent is memory-only, target-bound, same-owner/CSRF bound and consumed locally once",()=>{
 let now=1000,identity={owner:ID,csrfToken:"A",active:true};const action={operation:"email_change",email:"new@example.test"},vault=createIdentityIntentVault(ID,action,()=>identity,()=>now);
 assert.equal(vault.storeMail({request_id:ID,request_token:TOKEN,expires_at:new Date(now+1800000).toISOString()}),true);assert.equal(vault.acceptMail(action,"email_change_new",CODE),true);assert.equal(vault.mailReady(action),false);assert.equal(vault.acceptMail(action,"email_change_old","c".repeat(43)),true);assert.equal(vault.mailReady(action),true);assert.ok(!JSON.stringify(vault).includes(TOKEN));
 const body=vault.takeMail(action);assert.equal(body.email_token,CODE);assert.equal(body.old_email_token,"c".repeat(43));assert.equal(vault.takeMail(action),null);
 assert.equal(vault.storeMail({request_id:ID,request_token:TOKEN,expires_at:new Date(now+1800000).toISOString()}),true);assert.equal(vault.requestId({...action,email:"other@example.test"}),null);assert.equal(vault.requestId(action),null);
});
test("temporary authority checking hides pending intent while owner/CSRF replacement destroys it",()=>{
 let identity={owner:ID,csrfToken:"A",active:true};const action={operation:"password_add"},vault=createIdentityIntentVault(ID,action,()=>identity),issued={request_id:ID,request_token:TOKEN,expires_at:new Date(Date.now()+1700000).toISOString()};vault.storeMail(issued);vault.acceptMail(action,"password_add",CODE);
 identity={...identity,active:false};assert.equal(vault.requestId(action),null);assert.equal(vault.mailReady(action),false);identity={...identity,active:true};assert.equal(vault.mailReady(action),true);
 identity={...identity,csrfToken:"B"};assert.equal(vault.requestId(action),null);identity={...identity,csrfToken:"A"};assert.equal(vault.requestId(action),null);vault.storeMail(issued);identity={...identity,owner:OTHER};assert.equal(vault.requestId(action),null);
});
test("intent expiry, cancellation and wrong-purpose tickets cannot authorize completion",()=>{
 let now=1000;const action={operation:"password_add"},vault=createIdentityIntentVault(ID,action,()=>({owner:ID,active:true,csrfToken:"A"}),()=>now);assert.equal(vault.storeMail({request_id:ID,request_token:TOKEN,expires_at:new Date(now+1806000).toISOString()}),false);vault.storeMail({request_id:ID,request_token:TOKEN,expires_at:new Date(now+1000).toISOString()});assert.equal(vault.acceptMail(action,"email_change_old",CODE),false);vault.acceptMail(action,"password_add",CODE);now+=1000;assert.equal(vault.mailReady(action),false);vault.clear();assert.equal(vault.requestId(action),null);
});
test("identity flow has explicit start/final steps and uncertain mutations cannot replay",()=>{
 let state=identityFlowState("google_link");state=identityFlowReducer(state,{type:"verify"});state=identityFlowReducer(state,{type:"verified"});assert.equal(state.phase,"ready");state=identityFlowReducer(state,{type:"start"});state=identityFlowReducer(state,{type:"candidate",email:"observed@example.test"});assert.equal(state.phase,"candidate");state=identityFlowReducer(state,{type:"mutate"});state=identityFlowReducer(state,{type:"failed",uncertain:true});assert.equal(state.phase,"uncertain");assert.equal(identityFlowReducer(state,{type:"mutate"}).phase,"uncertain");state=identityFlowReducer(state,{type:"check"});state=identityFlowReducer(state,{type:"checked"});assert.equal(state.phase,"review");assert.match(state.reconcile,/unconfirmed/);
});
test("capability gating requires two actual snapshots and usable linked methods",()=>{
 const caps={recent_proof:true,password_add:true,email_change:true,google_link:true,google_unlink:true,session_revoke:true,sessions_revoke_all:true,password_change:false},data={profile:{capabilities:caps},methods:{capabilities:caps,password:{linked:false,available:false},google:{available:true,identities:[{id:ID}]}}};
 assert.equal(canAccountAction(data,{operation:"password_add"}),true);assert.equal(canAccountAction(data,{operation:"email_change"}),true);assert.equal(canAccountAction(data,{operation:"google_unlink",identity:{id:OTHER}}),false);assert.equal(canAccountAction({...data,profile:{capabilities:{...caps,google_link:false}}},{operation:"google_link"}),false);assert.notEqual(actionKey({operation:"email_change",email:"a@example.test"}),actionKey({operation:"email_change",email:"b@example.test"}));
});
test("notification consent starts off and edits/cancel never change saved consent",()=>{
 let state=notificationEditor();assert.equal(state.draft.in_app_success,false);state=notificationReducer(state,{type:"loaded",snapshot:snapshot()});state=notificationReducer(state,{type:"edit",key:"in_app_success",value:true});assert.equal(state.base.values.in_app_success,false);state=notificationReducer(state,{type:"cancel"});assert.equal(state.draft.in_app_success,false);
});
test("notification CAS conflicts preserve selection and require explicit reload/review",()=>{
 let state=notificationReducer(notificationEditor(),{type:"loaded",snapshot:snapshot()});state=notificationReducer(state,{type:"edit",key:"in_app_success",value:true});state=notificationReducer(state,{type:"save"});state=notificationReducer(state,{type:"failed",error:{status:409}});assert.equal(state.draft.in_app_success,true);assert.equal(notificationReducer(state,{type:"save"}).phase,"blocked");state=notificationReducer(state,{type:"check"});state=notificationReducer(state,{type:"checked",snapshot:snapshot(2,false)});assert.equal(state.phase,"review");state=notificationReducer(state,{type:"keep"});assert.equal(state.base.revision,2);assert.equal(state.draft.in_app_success,true);
});
test("lost notification save reconciles by GET, never implicit PUT retry",()=>{
 let state=notificationReducer(notificationEditor(),{type:"loaded",snapshot:snapshot()});state=notificationReducer(state,{type:"edit",key:"in_app_success",value:true});state=notificationReducer(state,{type:"save"});state=notificationReducer(state,{type:"failed",error:{status:0}});state=notificationReducer(state,{type:"check"});state=notificationReducer(state,{type:"checked",snapshot:snapshot(2,true)});assert.equal(state.phase,"editing");assert.match(state.status,/confirmed/);assert.equal(state.attempt,null);
});
test("optional notices require confirmed server consent and only new owned live completion",()=>{
 const identity={owner:ID,csrfToken:"A",active:true},gate=createLiveNoticeGate(ID,()=>identity),event={owner:ID,requestId:OTHER,previousStatus:"running",status:"complete",live:true,alreadyVisible:false};assert.equal(gate.observe(event),null);gate.confirm(snapshot(2,true),{owner:ID,csrfToken:"A"});for(const changed of [{...event,live:false},{...event,owner:OTHER},{...event,previousStatus:"complete"}])assert.equal(gate.observe(changed),null);assert.deepEqual(gate.observe(event),{id:OTHER,message:"Your request is complete."});assert.equal(gate.observe(event),null);assert.ok(!JSON.stringify(gate).includes(OTHER));
});
test("notices never duplicate visible completion and auth changes clear consent",()=>{
 let identity={owner:ID,csrfToken:"A",active:true};const gate=createLiveNoticeGate(ID,()=>identity),event={owner:ID,requestId:OTHER,previousStatus:"pending",status:"complete",live:true,alreadyVisible:true};gate.confirm(snapshot(2,true),{owner:ID,csrfToken:"A"});assert.equal(gate.observe(event),null);assert.equal(gate.observe({...event,alreadyVisible:false}),null);identity={...identity,active:false};assert.equal(gate.observe({...event,alreadyVisible:false}),null);identity={...identity,active:true};assert.equal(gate.observe({...event,alreadyVisible:false}),null);gate.confirm({...snapshot(3,true),values:values(true,"hidden")},{owner:ID,csrfToken:"A"});assert.equal(gate.observe({...event,alreadyVisible:false}),null);
});
test("mail parser rejects userinfo, normalized path aliases, unknown keys and encoded controls",()=>{
 const base=ORIGIN+"/account-action/password_add#request="+ID+"&token="+CODE,options={origin:ORIGIN,purpose:"password_add",requestId:ID};
 for(const value of [base.replace("https://","https://@"),base.replace("https://","https://user:secret@"),base.replace("/password_add","/other/../password_add"),base.replace("/password_add","/%70assword_add"),base+"&request="+ID,base+"&extra=x",base.replace("#request=","?query=yes#request="),base.replace(ID,ID.toUpperCase()),base.replace("&token=","&token=%0A"),base.replace("#request=","#token="+CODE+"&request=")])assert.throws(()=>parseAccountMailLink(value,options));
});
test("late notification consent cannot publish after owner or same-owner CSRF replacement",()=>{
 let identity={owner:ID,csrfToken:"A",active:true};const gate=createLiveNoticeGate(ID,()=>identity),old={owner:ID,csrfToken:"A"},event={owner:ID,requestId:OTHER,previousStatus:"running",status:"complete",live:true};
 identity={...identity,csrfToken:"B"};assert.equal(gate.confirm(snapshot(2,true),old),false);assert.equal(gate.observe(event),null);assert.equal(gate.confirm(snapshot(2,true),{owner:ID,csrfToken:"B"}),true);
 identity={...identity,owner:OTHER};assert.equal(gate.confirm(snapshot(3,true),{owner:ID,csrfToken:"B"}),false);assert.equal(gate.observe(event),null);
});
test("notification request scope prevents late settings GET and CAS completion across authority generations",()=>{
 let identity={owner:ID,csrfToken:"A",active:true};const scope=createAccountRequestScope(ID,()=>identity),get=scope.begin("notifications");identity={...identity,active:false};assert.equal(get.current(),false);scope.abort();identity={...identity,active:true};assert.equal(get.current(),false);const save=scope.begin("notifications");identity={...identity,csrfToken:"B"};assert.equal(save.current(),false);const fresh=scope.begin("notifications");assert.equal(fresh.current(),true);identity={...identity,owner:OTHER};assert.equal(fresh.current(),false);scope.dispose();
});
test("Google SDK callbacks are single-use and cannot run after cancel, target replacement or expiry",()=>{
 let now=1000,current;const request={challenge:{expires_at:new Date(2000).toISOString()},current:()=>true};current=request;
 let gate=createGoogleCallbackGate(request,()=>current,()=>now);assert.equal(gate.claim(),true);assert.equal(gate.claim(),false);
 gate=createGoogleCallbackGate(request,()=>current,()=>now);gate.dispose();assert.equal(gate.claim(),false);
 gate=createGoogleCallbackGate(request,()=>current,()=>now);current={...request};assert.equal(gate.claim(),false);
 current=request;gate=createGoogleCallbackGate(request,()=>current,()=>now);now=2000;assert.equal(gate.claim(),false);assert.equal(gate.expire(),true);assert.equal(gate.expire(),false);
});
test("Google callback gate uses the exact owner and CSRF request fence before transport",()=>{
 let identity={owner:ID,csrfToken:"A",active:true};const scope=createAccountRequestScope(ID,()=>identity),request={...scope.begin("proof"),challenge:{expires_at:new Date(Date.now()+10000).toISOString()}};let current=request;const gate=createGoogleCallbackGate(request,()=>current);
 identity={...identity,csrfToken:"B"};assert.equal(gate.claim(),false);identity={...identity,csrfToken:"A",owner:OTHER};assert.equal(gate.claim(),false);scope.abort();identity={owner:ID,csrfToken:"A",active:true};assert.equal(gate.claim(),false);scope.dispose();
});
test("identity browser checks copied then current session authority with ordinary GET only",async()=>{
 const calls=[],ctx={probeCopiedSession:async token=>{calls.push(["copied",token]);return 401;},rawRequest:async(...args)=>{calls.push(["current",...args]);return {status:401};}};
 await assertIdentitySessionsEnded(ctx,TOKEN);assert.deepEqual(calls,[["copied",TOKEN],["current","GET","/api/auth/me"]]);
});
test("identity browser rejects either copied or current access surviving a mutation",async()=>{
 for(const [copied,current,code] of [[200,401,"identity_mutation_session_survived"],[401,200,"identity_current_browser_session_survived"]]){
  let reads=0;const ctx={probeCopiedSession:async()=>copied,rawRequest:async()=>{reads++;return {status:current};}};
  await assert.rejects(assertIdentitySessionsEnded(ctx,TOKEN),{message:code});assert.equal(reads,copied===401?1:0);
 }
});
test("identity browser propagates failed authority requests without retry or sign-in",async()=>{
 for(const failed of ["copied","current"]){
  const error=Error("synthetic_network_failure"),calls=[],ctx={probeCopiedSession:async()=>{calls.push("copied");if(failed==="copied")throw error;return 401;},rawRequest:async()=>{calls.push("current");throw error;}};
  await assert.rejects(assertIdentitySessionsEnded(ctx,TOKEN),caught=>caught===error);assert.deepEqual(calls,failed==="copied"?["copied"]:["copied","current"]);
 }
});
test("identity browser restores current cookie provenance before the unchanged Google nonce seam",async()=>{
 const currentCookies={login:"synthetic-current-login"},nonce=CODE,client_id="synthetic-client",calls=[];let fixtureCookies={...currentCookies};
 const ctx={secrets:new Set(),probeCopiedSession:async token=>{calls.push("copied");assert.equal(token,TOKEN);fixtureCookies={session:token};return 401;},rawRequest:async(method,route)=>{calls.push("current");assert.equal(method,"GET");assert.equal(route,"/api/auth/me");fixtureCookies={...currentCookies};return {status:401};},waitFor:async()=>{},evaluate:async expression=>expression.startsWith("({nonce:")?{nonce,client_id}:true,click:async selector=>{assert.equal(selector,"[data-identity-google-fixture]");calls.push("click");},bridge:{send:async(kind,body)=>{calls.push("assertion");assert.equal(kind,"google_assertion");assert.deepEqual(body,{nonce,client_id,identity:"candidate"});assert.deepEqual(fixtureCookies,currentCookies);return {credential:"synthetic-one-use",synthetic:true,real_google_sdk_calls:0};}}};
 await ctx.probeCopiedSession(TOKEN);await assert.rejects(googleCallback(ctx,"candidate"),{name:"AssertionError"});calls.length=0;
 await assertIdentitySessionsEnded(ctx,TOKEN);await googleCallback(ctx,"candidate");assert.deepEqual(calls,["copied","current","assertion","click"]);assert.equal(ctx.secrets.has("synthetic-one-use"),true);
});
test("email browser journeys start with Google and obtain a fresh owner-bound Google action proof",async()=>{
 for(const scenario of ["email","lost-email"]){
  assert.equal(identityStartsWithGoogle(scenario),true);const calls=[],ctx={secrets:new Set(),click:async selector=>calls.push(selector),fill:async()=>assert.fail("email journey must not create or reuse a signup password"),waitFor:async(expression,label)=>calls.push(label),evaluate:async expression=>expression.startsWith("({nonce:")?{nonce:CODE,client_id:"synthetic-client"}:true,bridge:{send:async(kind,body)=>{assert.deepEqual([kind,body],["google_assertion",{nonce:CODE,client_id:"synthetic-client",identity:"owner"}]);calls.push("fresh-assertion");return {credential:"synthetic-email-assertion",synthetic:true,real_google_sdk_calls:0};}}};
  await verifyIdentityMethod(ctx,{scenario,password:"unused",privateMarkup:async label=>calls.push(label)});
  assert.deepEqual(calls,["[data-account-start-google]","identity_google_control_ready","fresh-assertion","[data-identity-google-fixture]","identity_google_identity_proof_ready","Google assertion and action proof remain transient"]);
 }
 assert.equal(identityStartsWithGoogle("link"),false);assert.equal(identityStartsWithGoogle("unlink"),false);assert.throws(()=>identityStartsWithGoogle("other"));
});
test("email completion uses ordinary Google owner sign-in without password or registration replay",async()=>{
 for(const scenario of ["email","lost-email"]){const calls=[],ctx={secrets:new Set(),waitFor:async()=>{},evaluate:async expression=>expression.startsWith("({nonce:")?{nonce:CODE,client_id:"synthetic-client"}:true,fill:async()=>assert.fail("Google owner has no enrolled password"),click:async selector=>calls.push(selector),bridge:{send:async(kind,body)=>{assert.equal(kind,"google_assertion");assert.equal(body.identity,"owner");assert.equal(body.nonce,CODE);calls.push("ordinary-google-login");return {credential:"synthetic-owner-login",synthetic:true,real_google_sdk_calls:0};}}};await signInAfterIdentityChange(ctx,{scenario,email:"old@example.test",password:"unused",newPassword:"unused"});assert.deepEqual(calls,["ordinary-google-login","[data-identity-google-fixture]"]);}
});
test("email result requires the same owner, new app primary, old provider email and no new grant or method",()=>{
 const base={scenario:"email",owner:ID,email:"old@example.test",signed:{user:{id:ID,email:"p10c-new-reader@example.test"},can_query:false},methods:{password:{linked:false},google:{linked:true,identities:[{id:OTHER,email:"old@example.test"}]}}};
 for(const scenario of ["email","lost-email"])assert.doesNotThrow(()=>assertIdentityResult({...base,scenario}));
 for(const change of [v=>v.signed.user.id=OTHER,v=>v.signed.user.email="old@example.test",v=>v.signed.can_query=true,v=>v.methods.password.linked=true,v=>v.methods.google.linked=false,v=>v.methods.google.identities=[],v=>v.methods.google.identities[0].email="p10c-new-reader@example.test"]){const value=structuredClone(base);change(value);assert.throws(()=>assertIdentityResult(value));}
});
test("password enrollment and password-backed identity journeys retain their actual sign-in methods",async()=>{
 assert.equal(identityStartsWithGoogle("password-add"),true);assert.equal(identityStartsWithGoogle("notifications"),false);
 const calls=[],ctx={fill:async(...args)=>calls.push(args),click:async selector=>calls.push(selector),waitFor:async(expression,label)=>calls.push(label)};
 await verifyIdentityMethod(ctx,{scenario:"link",password:"private-password",privateMarkup:async label=>calls.push(label)});
 assert.deepEqual(calls,[["[data-account-current-password]","private-password"],"Current password never enters serialized markup or device storage","[data-account-verify-password]","identity_current_password_verified"]);calls.length=0;
 await signInAfterIdentityChange(ctx,{scenario:"password-add",email:"owner@example.test",password:"unused",newPassword:"new-private-password"});assert.deepEqual(calls,[["#auth-email","owner@example.test"],["#auth-password","new-private-password"],'[data-testid=password-auth-submit]']);
});
const lostEmailSnapshot=()=>({phase:"uncertain",confirmAbsent:true,startAbsent:true,verifyAbsent:true,reviewEnabled:true,alert:identityFlowReducer({...identityFlowState("email_change"),phase:"mutating"},{type:"failed",uncertain:true}).error,audit:[{route:"/api/v1/me/reauth/google-challenges",method:"POST"},{route:"/api/v1/me/reauth/google",method:"POST"},{route:"/api/v1/me/email-change-requests",method:"POST"},{route:"/api/v1/me/email",method:"PUT"}]});
test("lost email browser accepts the actual reducer warning with explicit review and exact one-use write sequence",()=>{
 const state=lostEmailSnapshot();assert.equal(state.alert.includes("unconfirmed"),false);assert.equal(lostEmailReviewReady(state),true);
 const predicate=Function("return ("+lostEmailReviewReady.toString()+")")();assert.equal(predicate(state),true);
});
test("lost email browser rejects success claims, missing review, replay controls and altered or repeated mutations",()=>{
 for(const change of [v=>v.phase="mail-confirm",v=>v.confirmAbsent=false,v=>v.startAbsent=false,v=>v.verifyAbsent=false,v=>v.reviewEnabled=false,v=>v.alert="The change is unconfirmed",v=>v.alert="Email changed successfully",v=>v.audit.pop(),v=>v.audit.push({...v.audit.at(-1)}),v=>v.audit[3].method="POST",v=>v.audit[2].route="/api/v1/me/password",v=>v.audit.reverse()]){const state=lostEmailSnapshot();change(state);assert.equal(lostEmailReviewReady(state),false);}
 assert.equal(lostEmailReviewReady(null),false);
});
