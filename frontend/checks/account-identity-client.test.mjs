import assert from "node:assert/strict";
import test from "node:test";
import * as client from "../src/settings/accountIdentityClient.js";
import { googleActionChallenge, googleCandidate, notificationSnapshot, mailRequest } from "../src/settings/accountIdentityContract.js";
import { actionTarget, actionEmail } from "../src/settings/accountSecurityContract.js";
import { WorkspaceError } from "../src/services/workspaceClient.js";
const ID="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",OTHER="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",TOKEN="v2."+"a".repeat(43),PROOF="v2."+"b".repeat(43),CODE="c".repeat(43),SECRET="private-synthetic-secret";
const challenge=()=>({schemaVersion:1,challenge_id:ID,challenge_token:TOKEN,expires_at:new Date(Date.now()+240000).toISOString(),client_id:"synthetic-client.apps.googleusercontent.com",nonce:"n".repeat(43)});
const notification=()=>({schemaVersion:1,user_id:ID,revision:1,values:{in_app_success:false,preview:"generic"},capabilities:{in_app:true,browser:false,email:false,sound:false,quiet_hours:false}});
const mail=operation=>({schemaVersion:1,request_id:ID,request_token:TOKEN,expires_at:new Date(Date.now()+1700000).toISOString(),confirmation_required:operation==="password_add"?"primary_email":"old_and_new_email"});
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json"}});
test("twelve identity and notification routes have closed bodies and current-session CSRF",async t=>{
 const calls=[],issued=challenge(),snapshot=notification();t.mock.method(globalThis,"fetch",async(url,init)=>{calls.push({url,init});return json(url.endsWith("google-challenges")||url.endsWith("google-link-challenges")?issued:url.endsWith("/reauth/google")?{schemaVersion:1,proof_token:PROOF,expires_at:new Date(Date.now()+180000).toISOString()}:url.endsWith("google-link-candidates")?{schemaVersion:1,candidate_token:TOKEN,expires_at:new Date(Date.now()+180000).toISOString(),google:{email:"Candidate+tag@Example.test"}}:url.endsWith("password-enrollments")?mail("password_add"):url.endsWith("email-change-requests")?mail("email_change"):url.endsWith("notification-settings")?snapshot:{schemaVersion:1,[url.endsWith("google-links")?"linked":url.endsWith("revocations")?"unlinked":url.endsWith("/email")?"email_changed":"password_added"]:true,current_session_revoked:true});});
 const options={csrfToken:"synthetic-csrf",body:{owner_id:OTHER},method:"DELETE",expectedStatuses:[204]},target={operation:"google_link"};
 await client.createGoogleAccountChallenge(target,ID,options);await client.verifyAccountGoogle(target,issued,"header.payload.signature",options);await client.createGoogleLinkChallenge(PROOF,options);await client.verifyGoogleLinkCandidate(issued,"header.payload.signature",options);await client.linkAccountGoogle(PROOF,TOKEN,options);await client.unlinkAccountGoogle(ID,PROOF,options);await client.createPasswordEnrollment(PROOF,options);await client.addAccountPassword({proof_token:PROOF,request_id:ID,request_token:TOKEN,email_token:CODE,new_password:"Synthetic mountain password 49"},options);await client.createEmailChangeRequest(PROOF,"New+tag@Example.test",options);await client.changeAccountEmail({proof_token:PROOF,request_id:ID,request_token:TOKEN,email_token:CODE,old_email_token:"d".repeat(43)},options);await client.readNotificationSettings(ID,options);await client.saveNotificationSettings(ID,{expectedRevision:1,in_app_success:false,preview:"generic"},options);
 assert.deepEqual(calls.map(({url,init})=>[url,init.method]),[["/api/v1/me/reauth/google-challenges","POST"],["/api/v1/me/reauth/google","POST"],["/api/v1/me/google-link-challenges","POST"],["/api/v1/me/google-link-candidates","POST"],["/api/v1/me/google-links","POST"],[`/api/v1/me/methods/google/${ID}/revocations`,"POST"],["/api/v1/me/password-enrollments","POST"],["/api/v1/me/password","POST"],["/api/v1/me/email-change-requests","POST"],["/api/v1/me/email","PUT"],["/api/v1/me/notification-settings","GET"],["/api/v1/me/notification-settings","PUT"]]);
 assert.deepEqual(JSON.parse(calls[0].init.body),{operation:"google_link",identity_id:ID});assert.deepEqual(JSON.parse(calls[1].init.body),{operation:"google_link",challenge_id:ID,challenge_token:TOKEN,credential:"header.payload.signature"});assert.equal(JSON.parse(calls[8].init.body).new_email,"new+tag@example.test");
 for(const {init}of calls){assert.equal(init.credentials,"same-origin");assert.equal(init.mode,"same-origin");assert.equal(init.redirect,"error");assert.equal(init.cache,"no-store");assert.equal(init.referrerPolicy,"no-referrer");if(init.method!=="GET")assert.equal(init.headers["X-CSRF-Token"],"synthetic-csrf");else{assert.equal(init.body,undefined);assert.equal(init.headers["X-CSRF-Token"],undefined);}}
});
test("identity targets are operation-specific and normalize ASCII email without plus or dot rewriting",()=>{
 assert.deepEqual(actionTarget({operation:"google_unlink",target_identity_id:ID}),{operation:"google_unlink",target_identity_id:ID});assert.deepEqual(actionTarget({operation:"email_change",new_email:"A.B+Tag@Example.test"}),{operation:"email_change",new_email:"a.b+tag@example.test"});
 for(const value of [{operation:"google_unlink"},{operation:"email_change"},{operation:"google_link",target_identity_id:ID},{operation:"password_add",new_email:"a@example.test"},{operation:"email_change",new_email:"a@example.test",owner_id:ID}])assert.throws(()=>actionTarget(value));
 for(const value of [" a@example.test","a@example.test\n","a..b@example.test","a@-example.test","a@example","a@éxample.test"])assert.throws(()=>actionEmail(value));
});
test("Google challenge/candidate decoders reject added authority and malformed/late provider metadata",()=>{
 const issued=challenge();assert.equal(googleActionChallenge(issued).nonce,issued.nonce);
 for(const change of [r=>r.owner_id=ID,r=>r.nonce="bad",r=>r.client_id="https://private.test",r=>r.challenge_id=ID.toUpperCase(),r=>r.expires_at=new Date(Date.now()+306000).toISOString()]){const value=structuredClone(issued);change(value);assert.throws(()=>googleActionChallenge(value));}
 const candidate={schemaVersion:1,candidate_token:TOKEN,expires_at:new Date(Date.now()+180000).toISOString(),google:{email:"Observed+Tag@Example.test"}};assert.equal(googleCandidate(candidate,issued).google.email,candidate.google.email);
 for(const value of [{...candidate,google:{...candidate.google,verified:true}},{...candidate,expires_at:new Date(Date.now()+250000).toISOString()},{...candidate,subject:SECRET}])assert.throws(()=>googleCandidate(value,issued));
});
test("mail and notification snapshots are finite and owner-checked",()=>{
 const value=notification();assert.deepEqual(notificationSnapshot(value,ID),value);assert.throws(()=>notificationSnapshot(value,OTHER));
 for(const change of [r=>r.values.email=true,r=>r.capabilities.browser=true,r=>r.values.preview="full",r=>r.revision=0,r=>r.user_id=OTHER]){const bad=structuredClone(value);change(bad);assert.throws(()=>notificationSnapshot(bad,ID));}
 assert.equal(mailRequest(mail("password_add"),"password_add").confirmation_required,"primary_email");assert.throws(()=>mailRequest(mail("password_add"),"email_change"));assert.throws(()=>mailRequest({...mail("password_add"),expires_at:new Date(Date.now()+1806000).toISOString()},"password_add"));
});
test("malformed input is rejected before network and route IDs cannot escape",t=>{
 const fetch=t.mock.method(globalThis,"fetch",async()=>{throw Error("must not send");});
 for(const call of [()=>client.unlinkAccountGoogle("../other",TOKEN,{}),()=>client.linkAccountGoogle("bad",TOKEN,{}),()=>client.verifyAccountGoogle({operation:"google_link"},challenge(),"x".repeat(8193),{}),()=>client.saveNotificationSettings(ID,{expectedRevision:1,in_app_success:true,preview:"generic",email:true},{}),()=>client.changeAccountEmail({proof_token:PROOF,request_id:ID,request_token:TOKEN,email_token:CODE,old_email_token:CODE,owner_id:ID},{})])assert.throws(call,error=>error instanceof WorkspaceError&&error.code==="invalid_input");
 assert.equal(fetch.mock.calls.length,0);
});
test("lost or rejected mutations never retry, reflect response bodies or invent success",async t=>{
 const fetch=t.mock.method(globalThis,"fetch",async()=>{throw Error(SECRET+TOKEN);});await assert.rejects(client.linkAccountGoogle(PROOF,TOKEN,{csrfToken:"csrf"}),error=>error instanceof WorkspaceError&&!error.message.includes(SECRET)&&!JSON.stringify(error).includes(TOKEN));assert.equal(fetch.mock.calls.length,1);
 fetch.mock.mockImplementation(async()=>json({private:SECRET},409));await assert.rejects(client.createEmailChangeRequest(PROOF,"a@example.test",{csrfToken:"csrf"}),error=>error.status===409&&!error.message.includes(SECRET));assert.equal(fetch.mock.calls.length,2);
});
test("notification save rejects foreign owner, stale revision and changed server values",async t=>{
 for(const change of [r=>r.user_id=OTHER,r=>r.revision=1,r=>r.values.in_app_success=false]){const value=notification();value.revision=2;value.values.in_app_success=true;change(value);const fetch=t.mock.method(globalThis,"fetch",async()=>json(value));await assert.rejects(client.saveNotificationSettings(ID,{expectedRevision:2,in_app_success:true,preview:"generic"},{csrfToken:"csrf"}),error=>error.code==="invalid_response");fetch.mock.restore();}
});
