import React,{useEffect,useLayoutEffect,useReducer,useRef}from'react';
import PreferenceDialog from'./PreferenceDialog.jsx';
import AccountProofStep from'./AccountProofStep.jsx';
import useAccountScope from'./useAccountScope.js';
import{createActionProofVault}from'./accountSecurityState.js';
import{startDataExport,readDataExportIntent}from'./dataExportClient.js';
import{EXPORT_SCOPE}from'./dataExportContract.js';
import{bindExportRequest}from'./dataExportState.js';
const reducer=(state,event)=>event.type==='phase'?{phase:event.phase,error:event.error||''}:state;
export default function ExportReviewDialog({auth,methods,allowed,onClose,onJob,onUncertain}){
 const intent=useRef(null),cancel=useRef(null),identity=useRef(null),scope=useAccountScope(auth),vault=useRef(null),locked=useRef(false),authority=useRef(auth.csrfToken),publication=useRef(null);if(!intent.current)intent.current=globalThis.crypto.randomUUID();
 const[state,dispatch]=useReducer(reducer,{phase:'review',error:''}),ref=useRef(state);ref.current=state;
 const active=auth.status==='authenticated'&&allowed;
 if(!publication.current||publication.current.csrf!==auth.csrfToken||publication.current.active!==active||publication.current.access!==auth.canQuery)publication.current={id:(publication.current?.id||0)+1,csrf:auth.csrfToken,active,access:auth.canQuery};
 const generation=publication.current.id;identity.current={owner:auth.user.id,csrfToken:auth.csrfToken,active,generation};
 const current=()=>identity.current.active&&identity.current.generation===generation;
 const beginRequest=channel=>bindExportRequest(scope.begin(channel),()=>identity.current);
 const action={operation:'data_export',intentId:intent.current};if(!vault.current)vault.current=createActionProofVault(auth.user.id,action,()=>identity.current);
 const clear=()=>vault.current.clear();
 const close=()=>{if(ref.current.phase==='submitting')return;scope.abort();clear();if(['uncertain','checking'].includes(ref.current.phase))onUncertain(intent.current);onClose();};
 useLayoutEffect(()=>()=>{scope.abort();clear();},[]);
 useLayoutEffect(()=>{const changed=authority.current!==auth.csrfToken;authority.current=auth.csrfToken;if(active&&!changed)return;scope.abort();clear();locked.current=false;if(ref.current.phase!=='review')dispatch({type:'phase',phase:['submitting','uncertain','checking'].includes(ref.current.phase)?'uncertain':'verify',error:'Sign-in changed. Verify again or check the unconfirmed export before continuing.'});},[active,auth.csrfToken]);
 useLayoutEffect(()=>{if(cancel.current?.closest('dialog[open]'))cancel.current.focus({preventScroll:true});},[state.phase]);
 useEffect(()=>{if(state.phase!=='confirm')return undefined;const timer=setTimeout(()=>{clear();dispatch({type:'phase',phase:'verify',error:'Verification expired. Verify again for this export.'});},Math.max(0,vault.current.deadline()-Date.now()));return()=>clearTimeout(timer);},[state.phase]);
 const submit=async()=>{if(!active||locked.current||ref.current.phase!=='confirm')return;const proof=vault.current.take(action);if(!proof){dispatch({type:'phase',phase:'verify',error:'Verify again for this export.'});return;}const request=beginRequest('export-start');if(!request)return;locked.current=true;dispatch({type:'phase',phase:'submitting'});
 try{const reply=await startDataExport(auth.user.id,{intent_id:intent.current,scope:EXPORT_SCOPE,proof_token:proof},{csrfToken:auth.csrfToken,signal:request.signal});if(!request.current()||!identity.current.active)return;onJob(reply.job);onClose();}
 catch(error){if(request.current()){clear();dispatch({type:'phase',phase:[403,404,409,422,429].includes(error?.status)?'verify':'uncertain',error:[403,404,409,422,429].includes(error?.status)?'The export was not accepted. Review access and verify again when available.':'AQUA could not confirm whether the export was accepted. Check this exact intent before starting another export.'});if(error?.status===401)void auth.refresh?.();}}
 finally{locked.current=false;request.finish();}};
 const check=async()=>{if(!active||locked.current||ref.current.phase!=='uncertain')return;const request=beginRequest('export-readback');if(!request)return;locked.current=true;dispatch({type:'phase',phase:'checking'});try{const reply=await readDataExportIntent(auth.user.id,intent.current,{signal:request.signal});if(!request.current()||!identity.current.active)return;onJob(reply.job);onClose();}catch(error){if(request.current()){dispatch({type:'phase',phase:'uncertain',error:error?.status===404?'No matching export is currently available. This does not confirm whether the earlier request was accepted.':'The export could not be checked. No new request was sent.'});if(error?.status===401)void auth.refresh?.();}}finally{locked.current=false;request.finish();}};
 return <PreferenceDialog title="Export personal data" onClose={close} busy={state.phase==='submitting'} className="account-security-dialog data-export-dialog" initialFocusRef={cancel}><div data-export-dialog-phase={state.phase}>
 {state.error&&<p className="settings-error" role="alert">{state.error}</p>}
 {state.phase==='review'&&<><p>Prepare a private JSON copy of your saved profile, preferences, notification choices, projects, prompts and chats. Unsaved browser drafts and credentials are excluded.</p><p>Stored assistant results are included only where your current data access permits them. The temporary export expires one hour after it is requested. It does not delete your data.</p><div className="settings-dialog-actions"><button ref={cancel} type="button" onClick={close}>Cancel</button><button type="button" disabled={!active} onClick={()=>dispatch({type:'phase',phase:'verify'})}>Continue to verification</button></div></>}
 {['verify','verifying'].includes(state.phase)&&<AccountProofStep key={generation} auth={auth} target={{operation:'data_export',target_intent_id:intent.current}} methods={methods} allowed={active} phase={state.phase} cancelRef={cancel} onClose={close} onStart={()=>{if(current())dispatch({type:'phase',phase:'verifying'});}} onProof={proof=>{if(!current())return;if(!vault.current.store(proof))throw Error('export_proof_unavailable');dispatch({type:'phase',phase:'confirm'});}} onFailure={()=>{if(!current())return;clear();dispatch({type:'phase',phase:'verify',error:'Verification could not be confirmed. Start fresh verification when available.'});}}/>}
 {state.phase==='confirm'&&<><p role="status">Your sign-in method is verified for this exact export. Confirm to queue it.</p><div className="settings-dialog-actions"><button ref={cancel} type="button" onClick={close}>Cancel</button><button type="button" data-create-private-export disabled={!active} onClick={submit}>Create export</button></div></>}
 {state.phase==='submitting'&&<p role="status">Requesting the export…</p>}
 {['uncertain','checking'].includes(state.phase)&&<><p>No export creation request will be replayed automatically.</p><div className="settings-dialog-actions"><button ref={cancel} type="button" onClick={close}>Close</button>{state.phase==='uncertain'?<button type="button" disabled={!active} data-check-export-intent onClick={check}>Check this export</button>:<p role="status">Checking this export…</p>}</div></>}
 </div></PreferenceDialog>;
}
