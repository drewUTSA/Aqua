import { WorkspaceError } from "../services/workspaceClient.js";
import { accountOwner } from "./accountContract.js";
import { assertUniqueJsonKeys } from "./strictJson.js";
import { exportStart,exportReply,exportList,exportIntent,exportCursor,exportJob,MAX_EXPORT_BYTES,EXPORT_FILENAME } from "./dataExportContract.js";
const invalid=()=>new WorkspaceError('invalid_response'),aborted=()=>new DOMException('Request cancelled','AbortError');
const input=normalize=>{try{return normalize();}catch{throw new WorkspaceError('invalid_input',422);}};
function csrf(value){if(typeof value!=='string'||!value||value.length>512||/[\r\n]/.test(value))throw new WorkspaceError('unauthenticated',401);return value;}
function rejected(response){const retry=response.headers.get('Retry-After'),seconds=/^\d{1,5}$/.test(retry||'')?Math.min(Number(retry),86400):null;return new WorkspaceError(({401:'unauthenticated',403:'forbidden',404:'not_found',409:'conflict',422:'invalid_input',429:'throttled'})[response.status]||'unavailable',response.status,seconds);}
async function read(reader,signal){if(signal.aborted)throw aborted();return new Promise((resolve,reject)=>{const stop=()=>{void reader.cancel().catch(()=>{});reject(aborted());};signal.addEventListener('abort',stop,{once:true});reader.read().then(resolve,reject).finally(()=>signal.removeEventListener('abort',stop));});}
async function metadata(path,method,body,{csrfToken,signal}={},decode){
 if(signal?.aborted)throw aborted();const controller=new AbortController(),cancel=()=>controller.abort();signal?.addEventListener('abort',cancel,{once:true});const timer=setTimeout(cancel,15000);let reader;const chunks=[];
 try{
  const response=await fetch('/api/v1'+path,{method,credentials:'same-origin',mode:'same-origin',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer',signal:controller.signal,headers:{Accept:'application/json',...(method==='POST'?{'Content-Type':'application/json','X-CSRF-Token':csrf(csrfToken)}:{})},...(body?{body:JSON.stringify(body)}:{})});
  if(controller.signal.aborted){await response.body?.cancel();throw aborted();}
  if(response.redirected||!(method==='POST'?[200,202]:[200]).includes(response.status)){await response.body?.cancel();throw rejected(response);}
  if(response.headers.get('Content-Type')?.split(';',1)[0].trim()!=='application/json'||!response.body?.getReader){await response.body?.cancel();throw invalid();}
  const length=response.headers.get('Content-Length');if(length!==null&&(!/^\d{1,8}$/.test(length)||Number(length)>16384)){await response.body.cancel();throw invalid();}
  reader=response.body.getReader();let size=0;while(true){const{done,value}=await read(reader,controller.signal);if(done)break;if(!(value instanceof Uint8Array))throw invalid();chunks.push(value);if(!value.byteLength||chunks.length>1024||(size+=value.byteLength)>16384)throw invalid();}
  if(controller.signal.aborted)throw aborted();const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
  try{const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);assertUniqueJsonKeys(text);return decode(JSON.parse(text));}catch{throw invalid();}finally{bytes.fill(0);}
 }catch(error){if(signal?.aborted)throw aborted();if(error instanceof WorkspaceError)throw error;throw new WorkspaceError(controller.signal.aborted?'unavailable':'invalid_response');}
 finally{clearTimeout(timer);signal?.removeEventListener('abort',cancel);if(reader){await reader.cancel().catch(()=>{});reader.releaseLock();}for(const chunk of chunks)chunk.fill(0);}
}
export function startDataExport(owner,body,options){const expected=input(()=>accountOwner(owner)),checked=input(()=>exportStart(body));return metadata('/me/data-exports','POST',checked,options,value=>exportReply(value,expected,{intentId:checked.intent_id}));}
export function readDataExport(owner,id,options){const expected=input(()=>accountOwner(owner)),jobId=input(()=>accountOwner(id));return metadata('/me/data-exports/'+jobId,'GET',null,options,value=>exportReply(value,expected,{jobId}));}
export function readDataExportIntent(owner,id,options){const expected=input(()=>accountOwner(owner)),intentId=input(()=>exportIntent(id));return metadata('/me/data-exports/by-intent/'+intentId,'GET',null,options,value=>exportReply(value,expected,{intentId}));}
export function listDataExports(owner,{cursor=null,...options}={}){const expected=input(()=>accountOwner(owner)),position=input(()=>exportCursor(cursor));return metadata('/me/data-exports'+(position===null?'':'?'+new URLSearchParams({cursor:position})),'GET',null,options,value=>exportList(value,expected));}
export async function downloadDataExport(value,{csrfToken,signal,current}={}){
 const job=input(()=>exportJob(value)),token=csrf(csrfToken);if(job.state!=='ready'||typeof current!=='function')throw new WorkspaceError('invalid_input',422);
 if(signal?.aborted||!current()||Date.now()>=Date.parse(job.expires_at))throw aborted();const controller=new AbortController(),cancel=()=>controller.abort();signal?.addEventListener('abort',cancel,{once:true});const timer=setTimeout(cancel,60000);let reader,result,success=false;const chunks=[];
 try{
  const response=await fetch('/api/v1/me/data-exports/'+job.id+'/download',{method:'GET',credentials:'same-origin',mode:'same-origin',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer',signal:controller.signal,headers:{Accept:'application/json','X-CSRF-Token':token}});
  if(controller.signal.aborted||!current()){await response.body?.cancel();throw aborted();}
  if(response.redirected||response.status!==200){await response.body?.cancel();throw rejected(response);}
  const type=response.headers.get('Content-Type')?.split(';',1)[0].trim(),disposition=response.headers.get('Content-Disposition');
  if(type!=='application/json'||!/^attachment;\s*filename="aqua-personal-data-v1\.json"$/i.test(disposition||'')||!/\bno-store\b/i.test(response.headers.get('Cache-Control')||'')||response.headers.get('X-Content-Type-Options')!=='nosniff'||!response.body?.getReader){await response.body?.cancel();throw invalid();}
  const length=response.headers.get('Content-Length'),encoding=response.headers.get('Content-Encoding');if(!encoding||encoding==='identity')if(length!==null&&(!/^\d{1,8}$/.test(length)||Number(length)!==job.byte_count)){await response.body.cancel();throw invalid();}
  reader=response.body.getReader();let size=0;while(true){if(!current())throw aborted();const{done,value}=await read(reader,controller.signal);if(controller.signal.aborted||!current()){value?.fill?.(0);throw aborted();}if(done)break;if(!(value instanceof Uint8Array))throw invalid();chunks.push(value);if(!value.byteLength||chunks.length>8192||(size+=value.byteLength)>job.byte_count||size>MAX_EXPORT_BYTES)throw invalid();}
  if(size!==job.byte_count)throw invalid();result=new Uint8Array(size);let offset=0;for(const chunk of chunks){result.set(chunk,offset);offset+=chunk.byteLength;}
  const hash=Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256',result)),byte=>byte.toString(16).padStart(2,'0')).join('');
  if(controller.signal.aborted||signal?.aborted||!current()||Date.now()>=Date.parse(job.expires_at))throw aborted();if(hash!==job.sha256)throw invalid();success=true;return result;
 }catch(error){if(signal?.aborted||!current())throw aborted();if(error instanceof WorkspaceError)throw error;throw new WorkspaceError(controller.signal.aborted?'unavailable':'invalid_response');}
 finally{clearTimeout(timer);signal?.removeEventListener('abort',cancel);if(reader){await reader.cancel().catch(()=>{});reader.releaseLock();}for(const chunk of chunks)chunk.fill(0);if(!success)result?.fill(0);}
}
export {EXPORT_FILENAME};
