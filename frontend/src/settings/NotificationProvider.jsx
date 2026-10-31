import React, { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { readNotificationSettings } from "./accountIdentityClient.js";
import { createLiveNoticeGate, sameNotificationValues } from "./notificationState.js";
import useAccountScope from "./useAccountScope.js";
import "../styles/notifications.css";
const EMPTY={confirm:()=>false,observe:()=>{}},Context=createContext(EMPTY);
export const useNotifications=()=>useContext(Context);

export default function NotificationProvider({auth,children}) {
  return auth.demoMode?<Context.Provider value={EMPTY}>{children}</Context.Provider>:<OwnedNotifications key={auth.user.id} auth={auth}>{children}</OwnedNotifications>;
}
function OwnedNotifications({auth,children}) {
  const identity=useRef(null),gate=useRef(null),snapshot=useRef(null),scope=useAccountScope(auth),generation=useRef(null),[queue,setQueue]=useState({generation:0,items:[]});
  const active=auth.status==="authenticated";
  if(!generation.current||generation.current.owner!==auth.user.id||generation.current.csrfToken!==auth.csrfToken||generation.current.status!==auth.status||generation.current.canQuery!==auth.canQuery)generation.current={id:(generation.current?.id||0)+1,owner:auth.user.id,csrfToken:auth.csrfToken,status:auth.status,canQuery:auth.canQuery};
  identity.current={owner:auth.user.id,csrfToken:auth.csrfToken,active:active&&auth.canQuery===true};
  if(!gate.current)gate.current=createLiveNoticeGate(auth.user.id,()=>identity.current);
  const confirm=useCallback((next,expected)=>{
    if(!identity.current.active||next.user_id!==identity.current.owner||expected?.owner!==identity.current.owner||expected?.csrfToken!==identity.current.csrfToken)return false;
    const previous=snapshot.current;
    if(previous&&(next.revision<previous.revision||next.revision===previous.revision&&!sameNotificationValues(next.values,previous.values)))return false;
    snapshot.current=next;
    const accepted=gate.current.confirm(next,expected);if(!next.values.in_app_success||next.values.preview==="hidden")setQueue({generation:generation.current.id,items:[]});return accepted;
  },[]);
  const observe=useCallback((event,expected)=>{if(expected!==generation.current||!identity.current.active)return;const issued=expected.id,notice=gate.current.observe({...event,owner:expected.owner});if(notice)setQueue(previous=>generation.current!==expected||!identity.current.active?{generation:generation.current.id,items:[]}:{generation:issued,items:[...(previous.generation===issued?previous.items:[]).filter(item=>item.id!==notice.id),notice].slice(-3)});},[]);
  // A retained callback from an earlier render cannot relabel an old owner's
  // completion with the current owner or publish across a CSRF/status change.
  const publication=generation.current;
  const context=useMemo(()=>({confirm,observe:event=>observe(event,publication)}),[confirm,observe,publication]);
  useLayoutEffect(()=>{scope.abort();snapshot.current=null;gate.current.reset();setQueue({generation:generation.current.id,items:[]});return()=>{gate.current.reset();snapshot.current=null;};},[auth.status,auth.csrfToken,auth.canQuery]);
  useEffect(()=>{
    if(!active||auth.canQuery!==true)return undefined;const request=scope.begin("notice-consent");if(!request)return undefined;
    const expected={owner:auth.user.id,csrfToken:auth.csrfToken};
    void readNotificationSettings(auth.user.id,{signal:request.signal}).then(next=>{if(request.current())confirm(next,expected);}).catch(()=>{/* Optional messages remain off until a same-generation server snapshot is confirmed. */}).finally(request.finish);
    return()=>{scope.abort();};
  },[active,auth.csrfToken,auth.user.id,auth.canQuery,confirm]);
  return <Context.Provider value={context}>{children}{active&&auth.canQuery===true&&queue.generation===generation.current.id&&queue.items.length>0&&<aside className="in-app-success-notices" aria-label="Optional in-app messages">{queue.items.map(item=><div key={item.id} className="in-app-success-notice"><p role="status">{item.message}</p><button type="button" aria-label="Dismiss success message" onClick={()=>setQueue(previous=>({...previous,items:previous.items.filter(value=>value.id!==item.id)}))}>Dismiss</button></div>)}</aside>}</Context.Provider>;
}
