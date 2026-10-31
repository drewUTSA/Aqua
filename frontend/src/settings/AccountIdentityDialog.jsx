import React, { useEffect, useId, useLayoutEffect, useReducer, useRef, useState } from "react";
import PreferenceDialog from "./PreferenceDialog.jsx";
import AccountProofStep from "./AccountProofStep.jsx";
import GoogleActionButton from "./GoogleActionButton.jsx";
import useAccountScope from "./useAccountScope.js";
import { createActionProofVault } from "./accountSecurityState.js";
import { createIdentityIntentVault, identityFlowReducer, identityFlowState } from "./accountIdentityState.js";
import { createGoogleLinkChallenge, verifyGoogleLinkCandidate, linkAccountGoogle, unlinkAccountGoogle, createPasswordEnrollment, addAccountPassword, createEmailChangeRequest, changeAccountEmail } from "./accountIdentityClient.js";
import { actionEmail } from "./accountSecurityContract.js";
import { parseAccountMailLink } from "./accountMailHandoff.js";
import { readAccount, readAccountMethods } from "./accountClient.js";
import { validateNewPassword } from "../components/auth/authFormPolicy.js";
const TITLES={google_link:"Link Google",google_unlink:"Remove Google identity",password_add:"Add a password",email_change:"Change email"};

export default function AccountIdentityDialog({auth,action,methods,allowed,onClose,onProfile,onMethods}) {
  const [state,dispatch]=useReducer(identityFlowReducer,action.operation,identityFlowState),stateRef=useRef(state);stateRef.current=state;
  const scope=useAccountScope(auth),owner=useRef(auth.user.id),authority=useRef(auth.csrfToken),identity=useRef(null),targetAction=useRef({...action}),proof=useRef(null),intent=useRef(null),linkRequest=useRef(null),locked=useRef(false);
  const cancel=useRef(null),emailInput=useRef(null),newPassword=useRef(null),confirmation=useRef(null),primaryLink=useRef(null),oldLink=useRef(null),id=useId();
  const [email,setEmail]=useState(""),[googleGeneration,setGoogleGeneration]=useState(0);
  const active=auth.status==="authenticated"&&allowed,authorityActive=auth.status==="authenticated";
  identity.current={owner:auth.user.id,csrfToken:auth.csrfToken,active};
  const setup=next=>{targetAction.current=next;proof.current=createActionProofVault(owner.current,next,()=>identity.current);intent.current=createIdentityIntentVault(owner.current,next,()=>identity.current);};
  if(!proof.current&&action.operation!=="email_change")setup({...action});
  const fields=[emailInput,newPassword,confirmation,primaryLink,oldLink],clearFields=()=>{for(const ref of fields)if(ref.current){ref.current.value="";ref.current.defaultValue="";}};
  const clear=()=>{proof.current?.clear();intent.current?.clear();clearFields();linkRequest.current=null;};
  const close=()=>{if(stateRef.current.phase==="mutating")return;scope.abort();clear();onClose();};
  useLayoutEffect(()=>()=>{clear();scope.abort();},[]);
  useLayoutEffect(()=>{
    const changed=authority.current!==auth.csrfToken||owner.current!==auth.user.id;authority.current=auth.csrfToken;
    if(active&&!changed)return;
    scope.abort();locked.current=false;proof.current?.clear();clearFields();linkRequest.current=null;
    const retainMail=!changed&&intent.current?.hasPending()===true;
    if(!retainMail)intent.current?.clear();
    if(stateRef.current.phase!=="details")dispatch({type:"interrupt",retainMail});
  },[active,auth.csrfToken,auth.user.id]);
  useLayoutEffect(()=>{if(["verify","ready","candidate","mail","mail-verify","mail-confirm","review"].includes(state.phase)&&cancel.current?.closest("dialog[open]"))cancel.current.focus({preventScroll:true});},[state.phase]);
  useEffect(()=>{
    if(!proof.current||!["ready","candidate","mail","mail-confirm"].includes(state.phase))return undefined;
    const deadline=proof.current.deadline();if(!deadline)return undefined;
    const timer=setTimeout(()=>{proof.current.clear();if(intent.current?.hasPending())dispatch({type:"reverify"});else{intent.current?.clear();dispatch({type:"interrupt",retainMail:false});}},Math.max(0,deadline-Date.now()));
    return()=>clearTimeout(timer);
  },[state.phase]);
  useEffect(()=>{
    if(!["mail","mail-confirm","mail-verify","mail-verifying"].includes(state.phase)||!intent.current?.hasPending())return undefined;
    const timer=setTimeout(()=>{clear();dispatch({type:"failed",uncertain:false});},Math.max(0,intent.current.mailDeadline()-Date.now()));return()=>clearTimeout(timer);
  },[state.phase]);
  const target=targetAction.current.operation==="email_change"?{operation:"email_change",new_email:targetAction.current.email}:targetAction.current.operation==="google_unlink"?{operation:"google_unlink",target_identity_id:action.identity.id}:{operation:action.operation};
  const details=event=>{event.preventDefault();if(!active||stateRef.current.phase!=="details")return;let value;try{value=actionEmail(emailInput.current?.value||"");}catch{dispatch({type:"invalid-email"});return;}clearFields();setup({...action,email:value});setEmail(value);dispatch({type:"details"});};
  const options=request=>({csrfToken:auth.csrfToken,signal:request.signal});
  const fail=(error,request,mutation=false)=>{if(request.current()){clear();dispatch({type:"failed",uncertain:mutation&&![403,404,409,422,429].includes(error?.status)});if(error?.status===401)void auth.refresh?.();}locked.current=false;request.finish();};
  const begin=async()=>{
    if(!active||locked.current||stateRef.current.phase!=="ready")return;
    const token=proof.current.peek(targetAction.current);if(!token){dispatch({type:"interrupt",retainMail:false});return;}
    const request=scope.begin("identity");if(!request)return;locked.current=true;dispatch({type:"start"});
    try{
      if(action.operation==="google_link"){
        const challenge=await createGoogleLinkChallenge(token,options(request));if(!request.current())return;
        linkRequest.current={...request,challenge,csrfToken:auth.csrfToken};setGoogleGeneration(value=>value+1);return;
      }
      const pending=action.operation==="password_add"?await createPasswordEnrollment(token,options(request)):await createEmailChangeRequest(token,targetAction.current.email,options(request));
      if(!request.current())return;if(!intent.current.storeMail(pending))throw Error();dispatch({type:"mail"});locked.current=false;request.finish();
    }catch(error){fail(error,request);}
  };
  const candidate=async(credential,request)=>{
    if(linkRequest.current!==request||!request.current())return;
    try{const value=await verifyGoogleLinkCandidate(request.challenge,credential,{csrfToken:request.csrfToken,signal:request.signal});if(!request.current())return;
      if(!intent.current.storeCandidate(value))throw Error();linkRequest.current=null;dispatch({type:"candidate",email:value.google.email});locked.current=false;request.finish();
    }catch(error){fail(error,request);}
  };
  const acceptLink=(ref,purpose)=>{
    const raw=ref.current?.value||"";if(ref.current){ref.current.value="";ref.current.defaultValue="";}
    if(!active||!intent.current)return;
    try{const requestId=intent.current.requestId(targetAction.current);if(!requestId)throw Error();const token=parseAccountMailLink(raw,{origin:window.location.origin,purpose,requestId});if(!intent.current.acceptMail(targetAction.current,purpose,token))throw Error();
      const ready=intent.current.mailReady(targetAction.current);dispatch({type:"mail-received",count:ready?action.operation==="email_change"?2:1:1});if(ready)dispatch({type:"mail-ready",proofReady:Boolean(proof.current.peek(targetAction.current))});
    }catch{dispatch({type:"invalid-link"});}
  };
  const commit=async event=>{
    event.preventDefault();if(!active||locked.current||!["ready","candidate","mail-confirm"].includes(stateRef.current.phase))return;
    const password=newPassword.current?.value||"",repeat=confirmation.current?.value||"";
    if(action.operation==="password_add"&&validateNewPassword(password,repeat)){clearFields();dispatch({type:"invalid-password"});return;}
    const token=proof.current.take(targetAction.current);if(!token){clearFields();dispatch({type:"interrupt",retainMail:intent.current?.hasPending()===true});return;}
    const extra=action.operation==="google_link"?intent.current.takeCandidate(targetAction.current):["email_change","password_add"].includes(action.operation)?intent.current.takeMail(targetAction.current):null;
    if(action.operation!=="google_unlink"&&!extra){clear();dispatch({type:"failed",uncertain:false});return;}
    const request=scope.begin("identity");if(!request)return;locked.current=true;clearFields();dispatch({type:"mutate"});
    try{
      if(action.operation==="google_link")await linkAccountGoogle(token,extra,options(request));
      else if(action.operation==="google_unlink")await unlinkAccountGoogle(action.identity.id,token,options(request));
      else if(action.operation==="password_add")await addAccountPassword({proof_token:token,...extra,new_password:password},options(request));
      else await changeAccountEmail({proof_token:token,...extra},options(request));
      if(!request.current())return;clear();onClose();auth.sessionEnded?.();
    }catch(error){fail(error,request,true);}finally{request.finish();locked.current=false;}
  };
  const reconcile=async()=>{
    if(!authorityActive||locked.current||stateRef.current.phase!=="uncertain")return;const request=scope.begin("identity");if(!request)return;locked.current=true;dispatch({type:"check"});
    try{const profile=await readAccount(auth.user.id,{signal:request.signal});if(!request.current())return;const methods=await readAccountMethods({signal:request.signal});if(!request.current())return;onProfile?.(profile);onMethods?.(methods);dispatch({type:"checked"});}
    catch(error){if(request.current()){dispatch({type:"check-failed"});if(error?.status===401)void auth.refresh?.();}}finally{request.finish();locked.current=false;}
  };
  const mailPhase=["mail","mail-confirm","mail-verify","mail-verifying"].includes(state.phase),mailReady=active&&intent.current?.mailReady(targetAction.current),mailInput=(ref,purpose,label)=><label className="account-security-field">{label}<input ref={ref} type="password" autoComplete="off" data-account-mail-link={purpose} disabled={!active||state.phase==="mail-verifying"} maxLength={2048}/><button type="button" disabled={!active||state.phase==="mail-verifying"} onClick={()=>acceptLink(ref,purpose)}>Use this confirmation link</button></label>;
  return <PreferenceDialog title={TITLES[action.operation]} onClose={close} busy={state.phase==="mutating"} className="account-security-dialog account-identity-dialog" initialFocusRef={cancel}>
    <div data-account-identity-phase={state.phase}><p>Confirmed account changes end every active session. You will need to sign in again. Linking a method never merges accounts or grants data access.</p>
      {email&&<p>New primary email: <strong>{email}</strong></p>}
      {state.error&&<p className="settings-error" role="alert">{state.error}</p>}
      {state.phase==="details"&&<form onSubmit={details}><label className="account-security-field" htmlFor={id}>New email<input ref={emailInput} id={id} type="email" autoComplete="email" maxLength={254} required disabled={!active}/></label><p>Both your current and new mailbox must confirm the change.</p><div className="settings-dialog-actions"><button ref={cancel} type="button" onClick={close}>Cancel</button><button type="submit" disabled={!active}>Continue to verification</button></div></form>}
      {["verify","verifying","mail-verify","mail-verifying"].includes(state.phase)&&<AccountProofStep auth={auth} target={target} methods={methods} allowed={active} phase={state.phase==="mail-verifying"?"verifying":state.phase==="mail-verify"?"verify":state.phase} cancelRef={cancel} onClose={close} onStart={()=>dispatch({type:"verify"})} onProof={value=>{if(!proof.current.store(value))throw Error();dispatch({type:"verified",mailPending:intent.current.hasPending(),mailReady:intent.current.mailReady(targetAction.current)});}} onFailure={()=>{proof.current.clear();dispatch({type:"verification-failed"});}}/>}
      {state.phase==="ready"&&action.operation!=="google_unlink"&&<><p role="status">Your sign-in method is verified for this action.</p><div className="settings-dialog-actions"><button ref={cancel} type="button" onClick={close}>Cancel</button><button type="button" disabled={!active} data-account-start-identity onClick={begin}>{action.operation==="google_link"?"Choose Google identity":"Send confirmation links"}</button></div></>}
      {state.phase==="starting"&&<><p role="status">{action.operation==="google_link"?"Choose the Google identity to link. It must be verified separately.":"Requesting confirmation links…"}</p>{linkRequest.current&&<GoogleActionButton generation={googleGeneration} getRequest={()=>linkRequest.current} onCredential={candidate} onUnavailable={()=>{const request=linkRequest.current;if(request)fail({},request);}}/>}<button ref={cancel} type="button" onClick={close}>Cancel</button></>}
      {state.phase==="candidate"&&<p role="status">Google reports <strong>{state.candidateEmail}</strong>. Review this identity before linking. This does not change your AQUA primary email.</p>}
      {mailPhase&&<><p>Paste the complete confirmation link from the matching mailbox. Keep this original tab open. A reload, closed tab or different browser requires a new action.</p>{mailInput(primaryLink,action.operation==="password_add"?"password_add":"email_change_new",action.operation==="password_add"?"Primary mailbox confirmation link":"New mailbox confirmation link")}{action.operation==="email_change"&&mailInput(oldLink,"email_change_old","Current mailbox confirmation link")}<p role="status">{mailReady?"Required confirmation links are held for this action.":state.mailReceived?"One matching confirmation link is held. Add the other mailbox’s link.":"Waiting for confirmation links."}</p>{["mail","mail-confirm"].includes(state.phase)&&<button type="button" disabled={!active} onClick={()=>{proof.current.clear();dispatch({type:"reverify"});}}>Verify again for this action</button>}</>}
      {(state.phase==="candidate"||state.phase==="ready"&&action.operation==="google_unlink"||state.phase==="mail-confirm")&&<form onSubmit={commit}>
        {action.operation==="password_add"&&<><label className="account-security-field">New password<input ref={newPassword} type="password" autoComplete="new-password" maxLength={1024} required disabled={!active}/></label><label className="account-security-field">Confirm new password<input ref={confirmation} type="password" autoComplete="new-password" maxLength={1024} required disabled={!active}/></label><p>Use 15–128 characters. Common or compromised passwords are rejected; passwords are never truncated.</p></>}
        <div className="settings-dialog-actions"><button ref={cancel} type="button" onClick={close}>Cancel</button><button type="submit" data-account-confirm-identity disabled={!active||state.phase==="mail-confirm"&&!mailReady}>{action.operation==="google_link"?"Link Google and sign out":action.operation==="google_unlink"?"Remove this Google identity and sign out":action.operation==="password_add"?"Add password and sign out":"Change email and sign out"}</button></div></form>}
      {state.phase==="mail"&&<button ref={cancel} type="button" onClick={close}>Cancel</button>}
      {state.phase==="mutating"&&<p role="status">Confirming the account change…</p>}
      {state.phase==="uncertain"&&<div className="settings-dialog-actions"><button ref={cancel} type="button" onClick={close}>Close</button><button type="button" disabled={!authorityActive} onClick={reconcile}>Check current access</button></div>}
      {state.phase==="checking"&&<><p role="status">Checking current access…</p><button ref={cancel} type="button" onClick={close}>Close</button></>}
      {state.phase==="review"&&<><p role="status">{state.reconcile}</p><button ref={cancel} type="button" onClick={close}>Close and review account</button></>}
      {!allowed&&<p>This action is currently unavailable. Review your linked sign-in methods.</p>}
    </div>
  </PreferenceDialog>;
}
