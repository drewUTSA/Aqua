import { exportJob,EXPORT_FILENAME } from "./dataExportContract.js";
// Capture the privacy authority generation as well as the account request.
// Returning to an earlier CSRF or capability value cannot revive this handle.
export function bindExportRequest(request,currentIdentity){
 if(!request)return null;const generation=currentIdentity()?.generation;
 return{...request,current:()=>request.current()&&currentIdentity()?.active===true&&currentIdentity()?.generation===generation};
}
export const initialExportPanel=()=>({phase:'idle',job:null,jobs:[],nextCursor:null,error:'',status:'',pendingIntent:null});
export function exportPanelReducer(state,event){switch(event.type){
 case'review':return{...state,phase:'loading',error:'',status:''};
 case'listed':return{...state,phase:'idle',jobs:event.snapshot.jobs,nextCursor:event.snapshot.next_cursor,error:'',status:event.snapshot.jobs.length?'':'No retained exports are available.'};
 case'created':case'checked':return{...state,phase:'observing',job:event.job,pendingIntent:null,error:'',status:''};
 case'uncertain':return{...state,phase:'uncertain',pendingIntent:event.intent,error:'AQUA could not confirm whether the export was accepted. Check this intent before starting another export.',status:''};
 case'check':return{...state,phase:'checking',error:'',status:''};
 case'absent':return{...state,phase:'uncertain',error:'No matching export is currently available. This does not confirm whether the earlier request was accepted.'};
 case'failed':return{...state,phase:state.pendingIntent?'uncertain':state.job?'observing':'idle',error:event.message||'Export status is unavailable. Check again when your connection is available.',status:''};
 case'download':return state.job?.state==='ready'&&['idle','observing'].includes(state.phase)?{...state,phase:'downloading',error:'',status:''}:state;
 case'prepared':return state.phase==='downloading'&&state.job?.state==='ready'?{...state,phase:'file_prepared',error:'',status:'Your verified JSON file is prepared. Choose Save JSON file to ask your browser to save it.'}:state;
 case'offered':return state.phase==='file_prepared'?{...state,phase:'observing',status:'Download requested. Your browser controls whether and where the file is saved.'}:state;
 case'expired':return{...state,phase:'observing',job:state.job?{id:state.job.id,intent_id:state.job.intent_id,scope:state.job.scope,state:'expired',created_at:state.job.created_at,expires_at:state.job.expires_at}:null,error:'',status:'This temporary download is no longer available. Create a new export.'};
 case'interrupted':return{...state,phase:state.pendingIntent?'uncertain':state.job?'observing':'idle',error:'Export activity paused while sign-in was checked. Review current status after access is confirmed.',status:''};
 case'fresh':return{...state,phase:'idle',pendingIntent:null,error:'',status:''};
 default:return state;
}}
// Blob URLs and private bytes never enter the render reducer or browser stores.
export function createExportFileVault(owner,identity,{now=Date.now,urls=globalThis.URL,BlobType=globalThis.Blob}={}){
 let entry=null;const clear=()=>{if(entry)urls.revokeObjectURL(entry.url);entry=null;};
 const permitted=()=>entry&&identity()?.active===true&&identity()?.owner===owner&&identity()?.csrfToken===entry.csrf&&identity()?.access===entry.access&&identity()?.generation===entry.generation&&now()<entry.deadline;
 return{clear,store(value,bytes,expected){clear();try{const job=exportJob(value),current=identity();if(job.state!=='ready'||!(bytes instanceof Uint8Array)||bytes.byteLength!==job.byte_count||current?.active!==true||current.owner!==owner||expected?.owner!==owner||expected.csrfToken!==current.csrfToken||expected.generation!==current.generation||now()>=Date.parse(job.expires_at))return false;
 const blob=new BlobType([bytes],{type:'application/json'});entry={id:job.id,url:urls.createObjectURL(blob),csrf:current.csrfToken,access:current.access,generation:current.generation,deadline:Date.parse(job.expires_at)};return true;}finally{bytes?.fill(0);}},
 offer(id){if(!permitted()||entry.id!==id){clear();return null;}return{url:entry.url,filename:EXPORT_FILENAME};},deadline:()=>entry?.deadline||0};
}
