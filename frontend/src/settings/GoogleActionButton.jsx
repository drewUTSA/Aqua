import React, { useEffect, useRef, useState } from "react";
import { loadGoogleIdentity } from "../services/googleIdentity.js";
import { createGoogleCallbackGate } from "./googleActionState.js";

// This uses only the action-specific server nonce. It never calls the login
// facade, reads credential contents, or stores a Google credential in React.
export default function GoogleActionButton({ generation, getRequest, onCredential, onUnavailable }) {
  const container = useRef(null), [status, setStatus] = useState("loading");
  const handlers = useRef({ getRequest, onCredential, onUnavailable }); handlers.current = { getRequest, onCredential, onUnavailable };
  useEffect(() => {
    const node = container.current, request = handlers.current.getRequest();
    if (!node || !request?.current()) return undefined;
    let google,timer;
    const gate=createGoogleCallbackGate(request,()=>handlers.current.getRequest()),current=gate.current;
    setStatus("loading");
    void loadGoogleIdentity().then(sdk => {
      if (!current()) return;
      google = sdk;
      sdk.initialize({ client_id: request.challenge.client_id, nonce: request.challenge.nonce, auto_select: false, cancel_on_tap_outside: true,
        callback: result => { if (!gate.claim()) return; node.replaceChildren(); void handlers.current.onCredential(result?.credential, request); } });
      if (!current()) return;
      sdk.renderButton(node, { type: "standard", theme: "filled_black", size: "large", text: "continue_with", shape: "rectangular", width: Math.max(200, Math.min(400, Math.floor(node.clientWidth || 300))) });
      setStatus("ready");
      timer = setTimeout(() => { if (gate.expire()) { node.replaceChildren(); setStatus("unavailable"); handlers.current.onUnavailable(); } }, Math.max(0, Date.parse(request.challenge.expires_at) - Date.now()));
    }).catch(() => { if (current()) { gate.dispose();setStatus("unavailable"); handlers.current.onUnavailable(); } });
    return () => { gate.dispose();clearTimeout(timer); node.replaceChildren(); google?.cancel?.(); };
  }, [generation]);
  return <div className="account-google-action" aria-busy={status === "loading"}>
    <div ref={container} data-account-google-action aria-label="Verify with Google" />
    {status === "loading" && <p role="status">Loading Google verification…</p>}
    {status === "unavailable" && <p role="alert">Google verification is unavailable. Start a new verification when it is available.</p>}
  </div>;
}
