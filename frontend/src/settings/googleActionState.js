// One SDK callback belongs to one live server nonce/request. Disposing or
// replacing that request permanently prevents the callback from being claimed.
export function createGoogleCallbackGate(request,currentRequest,now=Date.now) {
  let closed=false,consumed=false;
  const owned=()=>!closed&&!consumed&&currentRequest()===request&&request.current();
  const current=()=>owned()&&now()<Date.parse(request.challenge.expires_at);
  return {current,claim(){if(!current())return false;consumed=true;return true;},expire(){if(!owned()||now()<Date.parse(request.challenge.expires_at))return false;consumed=true;return true;},dispose(){closed=true;}};
}
