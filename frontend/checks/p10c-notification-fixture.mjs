// Synthetic UI contract double only; actual CAS/consent uses the real DB gate.
export function notificationFixture(fixture) {
  const owners=new Map();
  return async({url,method,body,headers},reply)=>{
    if(url.pathname!=="/api/v1/me/notification-settings")return false;
    const respond=async(status,value={})=>{await reply(status,value);return true;};
    if(!["GET","PUT"].includes(method))return respond(405);
    if(!fixture.email||!fixture.session().user.id)return respond(401);
    if(url.search)return respond(422);
    const owner=fixture.session().user.id,previous=owners.get(owner)||{revision:1,values:{in_app_success:false,preview:"generic"}};
    if(method==="PUT"){
      if(headers.origin!==url.origin||headers["x-csrf-token"]!=="fixture-session-csrf")return respond(403);
      if(!body||Object.keys(body).sort().join(",")!=="expectedRevision,in_app_success,preview"||!Number.isSafeInteger(body.expectedRevision)||body.expectedRevision<1||typeof body.in_app_success!=="boolean"||!["generic","hidden"].includes(body.preview))return respond(422);
      if(body.expectedRevision!==previous.revision)return respond(409);
      if(body.in_app_success!==previous.values.in_app_success||body.preview!==previous.values.preview){if(previous.revision>=Number.MAX_SAFE_INTEGER)return respond(503);owners.set(owner,{revision:previous.revision+1,values:{in_app_success:body.in_app_success,preview:body.preview}});}
    }
    return respond(200,{schemaVersion:1,user_id:owner,...structuredClone(owners.get(owner)||previous),capabilities:{in_app:true,browser:false,email:false,sound:false,quiet_hours:false}});
  };
}
