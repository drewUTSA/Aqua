import React, { useEffect, useRef, useState } from "react";
import { loadGoogleIdentity } from "../../services/googleIdentity.js";

/** Keep Google's own supported control; credentials go only to the auth facade. */
export default function GoogleSignInButton({ auth, disabled = false }) {
  const containerRef = useRef(null);
  const [status, setStatus] = useState("loading");
  const config = auth.config;
  const available = auth.status === "signedout" && config && config.capabilities?.google_login !== false;
  useEffect(() => {
    if (!available || !containerRef.current) return undefined;
    const container = containerRef.current;
    let cancelled = false;
    let observer;
    let frame;
    let width = 0;
    setStatus("loading");
    void loadGoogleIdentity().then((google) => {
      if (cancelled) return;
      google.initialize({ client_id: config.client_id, nonce: config.nonce, auto_select: false, callback: ({ credential }) => { if (!cancelled) void auth.acceptCredential(credential); } });
      const render = () => {
        if (cancelled) return;
        const nextWidth = Math.max(200, Math.min(400, Math.floor(container.clientWidth || 300)));
        if (width === nextWidth) return;
        container.replaceChildren();
        google.renderButton(container, { type: "standard", theme: "filled_black", size: "large", text: "continue_with", shape: "rectangular", width: nextWidth });
        width = nextWidth;
        setStatus("ready");
      };
      const resized = () => {
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => { try { render(); } catch { if (!cancelled) setStatus("unavailable"); } });
      };
      render();
      if (typeof ResizeObserver !== "undefined") { observer = new ResizeObserver(resized); observer.observe(container); }
    }).catch(() => { if (!cancelled) setStatus("unavailable"); });
    return () => { cancelled = true; observer?.disconnect(); cancelAnimationFrame(frame); container.replaceChildren(); };
  }, [available, auth.acceptCredential, config]);
  const loading = auth.status === "loading" || (available && status === "loading");
  const unavailable = !loading && (!available || status === "unavailable");
  return <div className="auth-google" aria-busy={loading}>
    {available && status !== "unavailable" && <div className="auth-google__control" aria-disabled={disabled || undefined} inert={disabled || undefined}><div ref={containerRef} className="google-signin-button" data-testid="google-signin-button" aria-label="Continue with Google" /></div>}
    {loading && <p className="auth-note" role="status">Loading Google sign-in…</p>}
    {unavailable && <div className="auth-google__unavailable"><p className="auth-note" role="status">Google sign-in is temporarily unavailable.</p><button className="auth-link" type="button" disabled={disabled} onClick={() => void auth.refresh()}>Retry Google sign-in</button></div>}
    {auth.googleError && available && <p className="auth-error" role="alert">Google sign-in could not be completed. Please try again.</p>}
  </div>;
}
