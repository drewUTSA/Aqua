import { accountOwner, accountInstant } from "./accountContract.js";
import { actionRecord, actionToken } from "./accountSecurityContract.js";
export const EXPORT_SCOPE="personal_v1",MAX_EXPORT_BYTES=33554432,EXPORT_FILENAME="aqua-personal-data-v1.json";
export const EXPORT_STATES=Object.freeze(["queued","working","ready","expired","failed"]);
export const EXPORT_ERRORS=Object.freeze(["source_too_large","authority_changed","interrupted","unavailable","encoding_failed"]);
const requireValue=value=>{if(!value)throw Error("export_contract_invalid");};
export function exportIntent(value){accountOwner(value);requireValue(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value));return value;}
export function exportCursor(value){requireValue(value===null||typeof value==='string'&&value.length>0&&value.length<=1024&&/^[A-Za-z0-9_.-]+$/.test(value));return value;}
export function exportStart(value){actionRecord(value,["intent_id","scope","proof_token"]);requireValue(value.scope===EXPORT_SCOPE);return{intent_id:exportIntent(value.intent_id),scope:EXPORT_SCOPE,proof_token:actionToken(value.proof_token)};}
export function exportJob(value){
 const state=Object.getOwnPropertyDescriptor(value||{},'state')?.value;
 requireValue(EXPORT_STATES.includes(state));
 actionRecord(value,["id","intent_id","scope","state","created_at","expires_at",...(state==='ready'?["byte_count","sha256"]:state==='failed'?["error_code"]:[])]);
 accountOwner(value.id);exportIntent(value.intent_id);requireValue(value.scope===EXPORT_SCOPE);accountInstant(value.created_at);accountInstant(value.expires_at);
 requireValue(Date.parse(value.expires_at)-Date.parse(value.created_at)===3600000);
 if(state==='ready')requireValue(Number.isSafeInteger(value.byte_count)&&value.byte_count>0&&value.byte_count<=MAX_EXPORT_BYTES&&typeof value.sha256==='string'&&/^[a-f0-9]{64}$/.test(value.sha256));
 if(state==='failed')requireValue(EXPORT_ERRORS.includes(value.error_code));
 return {...value};
}
export function exportReply(value,owner,{jobId,intentId}={}){
 actionRecord(value,["schemaVersion","user_id","job"]);requireValue(value.schemaVersion===1&&accountOwner(value.user_id)===accountOwner(owner));const job=exportJob(value.job);
 requireValue((jobId===undefined||job.id===accountOwner(jobId))&&(intentId===undefined||job.intent_id===exportIntent(intentId)));return{schemaVersion:1,user_id:owner,job};
}
export function exportList(value,owner){
 actionRecord(value,["schemaVersion","user_id","jobs","next_cursor"]);requireValue(value.schemaVersion===1&&accountOwner(value.user_id)===accountOwner(owner));
 const items=value.jobs;requireValue(Array.isArray(items)&&items.length<=5&&Reflect.ownKeys(items).length===items.length+1&&Array.from({length:items.length},(_,index)=>Object.hasOwn(Object.getOwnPropertyDescriptor(items,String(index))||{},'value')).every(Boolean));
 const jobs=items.map(exportJob);requireValue(new Set(jobs.map(job=>job.id)).size===jobs.length&&new Set(jobs.map(job=>job.intent_id)).size===jobs.length);
 return{schemaVersion:1,user_id:owner,jobs,next_cursor:exportCursor(value.next_cursor)};
}
