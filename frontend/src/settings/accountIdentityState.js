import { actionKey } from "./accountSecurityState.js";
import { actionToken } from "./accountSecurityContract.js";
import { accountOwner } from "./accountContract.js";
import { mailToken } from "./accountIdentityContract.js";

// Pending mailbox and candidate bearers never enter the render reducer. A
// retained request may outlive a proof; reauthentication never extends it.
export function createIdentityIntentVault(owner, action, identity, now = Date.now) {
  const key = actionKey(action); let pending = null, candidate = null, csrf = null, tokens = {};
  const clear = () => { pending = null; candidate = null; csrf = null; tokens = {}; };
  const current = () => identity()?.owner === owner && identity()?.active === true && (csrf === null || identity()?.csrfToken === csrf);
  const permitted = expected => { let same=false;try{same=actionKey(expected)===key;}catch{}const value=identity();if(value?.owner!==owner||csrf!==null&&value?.csrfToken!==csrf||!same){clear();return false;}return value?.active===true; };
  return {
    clear,
    storeMail(value) { if(!current())return false;const expires=Date.parse(value.expires_at);if(!Number.isFinite(expires)||expires<=now()||expires>now()+1805000)return false;
      pending={ request_id:accountOwner(value.request_id),request_token:actionToken(value.request_token),expires_at:expires };csrf=identity()?.csrfToken;tokens={};return true; },
    storeCandidate(value) { if(!current())return false;const expires=Date.parse(value.expires_at);if(!Number.isFinite(expires)||expires<=now()||expires>now()+305000)return false;
      candidate={candidate_token:actionToken(value.candidate_token),expires_at:expires};csrf=identity()?.csrfToken;return true; },
    requestId(expected) { if(!permitted(expected))return null;if(!pending||pending.expires_at<=now()){pending=null;tokens={};return null;}return pending.request_id; },
    mailDeadline:()=>pending?.expires_at||0,
    hasPending:()=>Boolean(pending&&pending.expires_at>now()),
    acceptMail(expected,purpose,token) { if(!this.requestId(expected)||!["password_add","email_change_new","email_change_old"].includes(purpose))return false;
      if(action.operation==="password_add"?purpose!=="password_add":action.operation!=="email_change"||purpose==="password_add")return false;
      tokens[purpose]=mailToken(token);return true; },
    mailReady(expected) { return Boolean(this.requestId(expected)&&(action.operation==="password_add"?tokens.password_add:tokens.email_change_new&&tokens.email_change_old)); },
    takeMail(expected) { if(!this.mailReady(expected))return null;const result={request_id:pending.request_id,request_token:pending.request_token,email_token:action.operation==="password_add"?tokens.password_add:tokens.email_change_new,...(action.operation==="email_change"?{old_email_token:tokens.email_change_old}:{})};clear();return result; },
    takeCandidate(expected) { if(!permitted(expected)||!candidate||candidate.expires_at<=now()){candidate=null;return null;}const token=candidate.candidate_token;candidate=null;return token; }
  };
}

export const identityFlowState = operation => ({ phase:operation==="email_change"?"details":"verify", error:"", candidateEmail:"", mailReceived:0, reconcile:"" });
export function identityFlowReducer(state,event) {
  switch(event.type){
    case "details":return state.phase==="details"?{...state,phase:"verify",error:""}:state;
    case "verify":return ["verify","mail-verify"].includes(state.phase)?{...state,phase:state.phase==="mail-verify"?"mail-verifying":"verifying",error:""}:state;
    case "verified":return ["verifying","mail-verifying"].includes(state.phase)?{...state,phase:event.mailPending?event.mailReady?"mail-confirm":"mail":"ready",error:""}:state;
    case "verification-failed":return ["verifying","mail-verifying"].includes(state.phase)?{...state,phase:state.phase==="mail-verifying"?"mail-verify":"verify",error:"Verification could not be confirmed. Start a fresh verification when it is available."}:state;
    case "start":return state.phase==="ready"?{...state,phase:"starting",error:""}:state;
    case "candidate":return state.phase==="starting"?{...state,phase:"candidate",candidateEmail:event.email,error:""}:state;
    case "mail":return state.phase==="starting"?{...state,phase:"mail",error:""}:state;
    case "mail-received":return ["mail","mail-confirm","mail-verify"].includes(state.phase)?{...state,mailReceived:event.count,error:""}:state;
    case "mail-ready":return ["mail","mail-confirm","mail-verify"].includes(state.phase)?{...state,phase:event.proofReady?"mail-confirm":"mail-verify",error:""}:state;
    case "reverify":return ["mail","mail-confirm"].includes(state.phase)?{...state,phase:"mail-verify",error:""}:state;
    case "mutate":return ["ready","candidate","mail-confirm"].includes(state.phase)?{...state,phase:"mutating",error:""}:state;
    case "failed":return { ...state,phase:event.uncertain?"uncertain":"verify",error:event.uncertain?"AQUA could not confirm whether the change finished. Check current access before starting a new action.":"This action could not be completed. Review your account and start fresh verification.",candidateEmail:"" };
    case "interrupt":return ["mutating","uncertain","checking"].includes(state.phase)?{...state,phase:"uncertain",error:"The change is unconfirmed. Check current access before starting a new action."}:{...state,phase:event.retainMail?"mail-verify":"verify",error:"Verify again after your sign-in is confirmed.",candidateEmail:"",mailReceived:event.retainMail?state.mailReceived:0};
    case "invalid-link":return {...state,error:"Paste the complete confirmation link for this exact request from the expected mailbox. The link was not opened or sent."};
    case "invalid-email":return {...state,error:"Enter a valid email address using the supported ASCII mailbox format. Your current email has not changed."};
    case "invalid-password":return {...state,error:"Use 15–128 characters and enter the same new password twice."};
    case "check":return state.phase==="uncertain"?{...state,phase:"checking",error:""}:state;
    case "checked":return state.phase==="checking"?{...state,phase:"review",reconcile:"Current access was checked. The earlier change is unconfirmed; review account details before starting another action."}:state;
    case "check-failed":return state.phase==="checking"?{...state,phase:"uncertain",error:"Current access could not be confirmed. No change has been confirmed."}:state;
    default:return state;
  }
}
