import React, { useId, useLayoutEffect, useRef, useState } from "react";
import useAccountScope from "./useAccountScope.js";
import GoogleActionButton from "./GoogleActionButton.jsx";
import { createAccountChallenge, verifyAccountPassword } from "./accountSecurityClient.js";
import { createGoogleAccountChallenge, verifyAccountGoogle } from "./accountIdentityClient.js";

export default function AccountProofStep({ auth, target, methods, allowed, phase, cancelRef, onClose, onStart, onProof, onFailure }) {
  const scope = useAccountScope(auth), password = useRef(null), locked = useRef(false), issued = useRef(null), authority=useRef(auth.csrfToken),callbacks = useRef(null), id = useId();
  const [googleGeneration, setGoogleGeneration] = useState(0);
  callbacks.current = { onProof, onFailure };
  const active = allowed && auth.status === "authenticated", pending = phase === "verifying";
  const passwordAvailable = target.operation !== "password_add" && methods?.password?.linked === true && methods.password.available === true;
  const googleIdentities = methods?.google?.available === true ? methods.google.identities : [];
  const clearPassword = () => { if (password.current) { password.current.value = ""; password.current.defaultValue = ""; } };
  useLayoutEffect(() => () => { clearPassword(); scope.abort(); issued.current = null; }, []);
  useLayoutEffect(() => { const changed=authority.current!==auth.csrfToken;authority.current=auth.csrfToken;if (!active||changed) { clearPassword(); scope.abort(); issued.current = null; locked.current = false; } }, [active, auth.csrfToken]);
  const fail = (error, request) => { if (request.current()) { callbacks.current.onFailure(error); if (error?.status === 401) void auth.refresh?.(); } request.finish(); issued.current = null; locked.current = false; };
  const succeed = (proof, request) => { if (request.current()) callbacks.current.onProof(proof); request.finish(); issued.current = null; locked.current = false; };
  const verifyPassword = async event => {
    event.preventDefault(); const entered = password.current?.value || "";
    if (!active || pending || locked.current || !passwordAvailable || !entered) return;
    const request = scope.begin("proof"); if (!request) return;
    locked.current = true; clearPassword(); onStart();
    try { const challenge = await createAccountChallenge(target, { csrfToken: auth.csrfToken, signal: request.signal }); if (!request.current()) return;
      const proof = await verifyAccountPassword(target, challenge, entered, { csrfToken: auth.csrfToken, signal: request.signal }); succeed(proof, request); }
    catch (error) { fail(error, request); }
    finally { request.finish(); locked.current = false; }
  };
  const startGoogle = async identityId => {
    if (!active || pending || locked.current || !googleIdentities.some(item => item.id === identityId)) return;
    const request = scope.begin("proof"); if (!request) return;
    locked.current = true; clearPassword(); onStart();
    try { const challenge = await createGoogleAccountChallenge(target, identityId, { csrfToken: auth.csrfToken, signal: request.signal }); if (!request.current()) return;
      issued.current = { ...request, challenge, target, csrfToken: auth.csrfToken }; setGoogleGeneration(value => value + 1); }
    catch (error) { fail(error, request); }
  };
  const credential = async (value, request) => {
    if (issued.current !== request || !request.current()) return;
    try { const proof = await verifyAccountGoogle(request.target, request.challenge, value, { csrfToken: request.csrfToken, signal: request.signal }); succeed(proof, request); }
    catch (error) { fail(error, request); }
  };
  return <div data-account-proof-step>
    <p>Verify an available linked sign-in method for this exact action. Verification lasts at most five minutes and can be used once.</p>
    {passwordAvailable && <form onSubmit={verifyPassword}>
      <label className="account-security-field" htmlFor={id}>Current password<input ref={password} id={id} data-account-current-password type="password" autoComplete="current-password" autoCapitalize="none" spellCheck={false} required maxLength={1024} disabled={!active || pending} /></label>
      <div className="settings-dialog-actions"><button ref={cancelRef} type="button" onClick={onClose}>Cancel</button><button type="submit" data-account-verify-password disabled={!active || pending}>{pending ? "Verifying…" : "Verify password"}</button></div>
    </form>}
    {googleIdentities.length > 0 && <div className="account-proof-google"><p>Use the same Google identity you linked to AQUA. This does not claim multi-factor verification.</p>
      {googleIdentities.map((identity, index) => <button key={identity.id} type="button" data-account-start-google={index} disabled={!active || pending} onClick={() => startGoogle(identity.id)}>Verify {identity.email||"Google account"}{googleIdentities.length>1?` · ${index+1}`:""}</button>)}
      {issued.current && pending && <GoogleActionButton generation={googleGeneration} getRequest={() => issued.current} onCredential={credential} onUnavailable={() => { const request=issued.current;if(request)fail({},request); }} />}
    </div>}
    {!passwordAvailable && <div className="settings-dialog-actions"><button ref={cancelRef} type="button" onClick={onClose}>Cancel</button></div>}
    {!passwordAvailable && !googleIdentities.length && <p role="status">No linked sign-in method is currently available for verification.</p>}
  </div>;
}
