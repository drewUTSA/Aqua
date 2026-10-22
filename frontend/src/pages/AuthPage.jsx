import React, { useEffect, useRef, useState } from "react";
import GoogleSignInButton from "../components/auth/GoogleSignInButton.jsx";
import OpalBackdrop from "../components/auth/OpalBackdrop.jsx";
import { passwordFailureMessage, validateNewPassword } from "../components/auth/authFormPolicy.js";
import { completeEmailVerification, completePasswordReset, requestPasswordReset, requestRegistration } from "../services/passwordAuthClient.js";
import mark from "../assets/opal/auth/mark.svg";
import chat from "../assets/opal/auth/chat.svg";
import chart from "../assets/opal/auth/chart.svg";
import clock from "../assets/opal/auth/clock.svg";
import "../styles/auth-page.css";

export const AUTH_PATHS = ["/signin", "/register", "/forgot-password", "/check-email", "/registration-sent", "/verify-email", "/reset-password"];
const PROOF = /^[A-Za-z0-9_-]{43}$/;
const FORM_ACTIONS = {
  "/signin": "/api/v1/auth/password-login", "/register": "/api/v1/auth/registrations",
  "/forgot-password": "/api/v1/auth/password-reset-requests", "/verify-email": "/api/v1/auth/email-verifications",
  "/reset-password": "/api/v1/auth/password-resets"
};

function LocalLink({ to, onNavigate, className = "auth-link", children }) {
  return <a className={className} href={to} onClick={(event) => {
    if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { event.preventDefault(); onNavigate(to); }
  }}>{children}</a>;
}

function Policies({ onNavigate }) {
  return <div className="auth-policies"><p>By continuing, you agree to our Terms of Service and acknowledge our Privacy Policy.</p><nav aria-label="Policies"><LocalLink to="/privacy" onNavigate={onNavigate}>Privacy Policy</LocalLink><LocalLink to="/terms" onNavigate={onNavigate}>Terms of Service</LocalLink></nav></div>;
}

function PasswordField({ id, label = "Password", autoComplete = "current-password", describedBy, disabled = false, inputRef }) {
  const [visible, setVisible] = useState(false);
  return <div className="auth-field"><label htmlFor={id}>{label}</label><div className="auth-password">
    <input ref={inputRef} id={id} name={id} type={visible ? "text" : "password"} autoComplete={autoComplete} required maxLength={512} disabled={disabled} aria-describedby={describedBy} spellCheck="false" autoCapitalize="none" placeholder={autoComplete === "current-password" ? "Enter your password" : "Create a unique password"} />
    <button type="button" className="auth-password__toggle" aria-controls={id} aria-pressed={visible} aria-label={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`} disabled={disabled} onClick={() => setVisible((value) => !value)}>{visible ? "Hide" : "Show"}</button>
  </div></div>;
}

function EmailField({ disabled = false, autoComplete = "email" }) {
  return <div className="auth-field"><label htmlFor="auth-email">Email address</label><input id="auth-email" name="email" type="email" autoComplete={autoComplete} inputMode="email" autoCapitalize="none" spellCheck="false" maxLength={254} required disabled={disabled} placeholder="you@company.com" /></div>;
}

function AuthContent({ path, proof, onNavigate, onProofConsumed, auth }) {
  const heading = useRef(null);
  const password = useRef(null);
  const confirmation = useRef(null);
  const active = useRef(null);
  const submitting = useRef(false);
  const mounted = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [complete, setComplete] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [unavailable, setUnavailable] = useState(false);
  const isSignIn = path === "/signin";
  const isRegistration = path === "/register";
  const isRequest = path === "/forgot-password";
  const isVerification = path === "/verify-email";
  const isReset = path === "/reset-password";
  const signingOut = auth.status === "signingout";
  const logoutFailed = auth.status === "logoutfailed";
  const identityUnavailable = auth.status === "unavailable";
  const accountLocked = signingOut || logoutFailed || identityUnavailable;
  const isProof = isVerification || isReset;
  const validProof = typeof proof === "string" && PROOF.test(proof);
  const invalidProof = isProof && (!validProof || error?.code === "invalid_proof");
  const retrySeconds = Math.max(0, Math.ceil((retryAt - now) / 1000));
  const authBusy = ["loading", "signingin", "signingout"].includes(auth.status);
  const busy = pending || auth.passwordPending || authBusy;
  const disabledByPolicy = isSignIn && auth.config?.capabilities?.password_login === false;
  const disabled = busy || retrySeconds > 0 || unavailable || disabledByPolicy;
  useEffect(() => { mounted.current = true; heading.current?.focus({ preventScroll: true }); return () => { mounted.current = false; active.current?.abort(); }; }, []);
  useEffect(() => {
    const remaining = retryAt - Date.now();
    if (remaining <= 0) return undefined;
    const timer = setTimeout(() => setNow(Date.now()), Math.min(1000, remaining));
    return () => clearTimeout(timer);
  }, [retryAt, now]);
  const clearPasswords = () => { if (password.current) password.current.value = ""; if (confirmation.current) confirmation.current.value = ""; };
  const failed = (failure) => {
    setError(failure || { status: 503 });
    if (failure?.status === 429 && Number.isInteger(failure.retryAfterSeconds) && failure.retryAfterSeconds > 0) { setNow(Date.now()); setRetryAt(Date.now() + failure.retryAfterSeconds * 1000); }
    if (failure?.status >= 500) setUnavailable(true);
    if (failure?.code === "invalid_proof") onProofConsumed?.();
  };
  const submit = async (event) => {
    event.preventDefault();
    if (submitting.current || disabled || (isProof && invalidProof)) return;
    const data = new FormData(event.currentTarget);
    const suppliedPassword = data.get("auth-password") || "";
    if (isProof) {
      const message = validateNewPassword(suppliedPassword, data.get("auth-password-confirm") || "");
      if (message) { setError({ code: "local_policy", message }); password.current?.focus(); return; }
    }
    submitting.current = true; setPending(true); setError(null);
    const controller = new AbortController(); active.current = controller;
    try {
      if (isSignIn) {
        // The shared auth hook owns session adoption and stale-response fencing.
        await auth.authenticatePassword(data.get("email"), suppliedPassword);
      } else if (isRegistration || isRequest) {
        const request = isRegistration ? requestRegistration : requestPasswordReset;
        await request({ email: data.get("email"), signal: controller.signal });
        if (mounted.current && !controller.signal.aborted) onNavigate(isRegistration ? "/registration-sent" : "/check-email");
      } else if (isProof) {
        if (isReset) auth.sessionEnded?.();
        const finish = isVerification ? completeEmailVerification : completePasswordReset;
        await finish({ token: proof, password: suppliedPassword, signal: controller.signal });
        if (mounted.current && !controller.signal.aborted) {
          setComplete(true); onProofConsumed?.(); heading.current?.focus();
        }
      }
    } catch (failure) {
      if (mounted.current && !controller.signal.aborted && failure?.name !== "AbortError") failed(failure);
    } finally {
      // Another tab can revalidate while a slow reset is still uncommitted.
      // Relock after every submitted reset, including a lost/503 response.
      if (isReset) auth.sessionEnded?.();
      clearPasswords(); submitting.current = false; if (mounted.current) setPending(false);
    }
  };
  // The hook provides a typed error for login; Google availability stays independent.
  useEffect(() => { if (isSignIn && auth.passwordError) failed(auth.passwordError); }, [auth.passwordError, isSignIn]);
  let title = "Welcome back";
  let description = "Sign in to your AQUA workspace.";
  if (isRegistration) { title = "Create your workspace"; description = "Start with your email. You’ll create a password after verifying it."; }
  if (isRequest) { title = "Reset your password"; description = "Enter your email address and we’ll send a link if your account is eligible for password recovery."; }
  if (path === "/check-email") { title = "Check your inbox"; description = "If this address is eligible, you’ll receive password-reset instructions shortly."; }
  if (path === "/registration-sent") { title = "Verify your email"; description = "If this address is eligible, you’ll receive a link to finish setting up your account."; }
  if (isVerification) { title = "Create your password"; description = "Choose a unique password to finish verifying your email."; }
  if (isReset) { title = "Choose a new password"; description = "Set a new password for your AQUA account."; }
  if (invalidProof) { title = "Request a new link"; description = "This link is missing, invalid, expired or already used. Request a new email to continue."; }
  if (complete) { title = isVerification ? "Your account is ready" : "Password updated"; description = isVerification ? "Your email is verified. Sign in with your new password to continue. Data access is managed by your AQUA administrator." : "Your password has been changed and existing sessions have been signed out. Sign in again to continue."; }
  if (signingOut) { title = "Signing you out…"; description = "Your workspace is locked while AQUA confirms sign-out."; }
  if (logoutFailed) { title = "Sign-out could not be confirmed"; description = "Your workspace is locked. Try signing out again to finish securely."; }
  if (identityUnavailable) { title = "Account access unavailable"; description = "AQUA couldn’t check your session. Please try again."; }
  useEffect(() => { document.title = `${title} | AQUA`; }, [title]);
  const hasForm = !accountLocked && !complete && !invalidProof && (isSignIn || isRegistration || isRequest || isProof);
  return <section className="auth-card" aria-labelledby="auth-title" aria-busy={busy} data-auth-view={path}>
    <header className="auth-card__header"><h1 id="auth-title" ref={heading} tabIndex={-1}>{title}</h1><p>{description}</p></header>
    {hasForm && <form onSubmit={submit} method="post" action={FORM_ACTIONS[path]} className="auth-form" data-testid="password-auth-form">
      {!isProof && <EmailField disabled={busy} autoComplete={isSignIn ? "username" : "email"} />}
      {(isSignIn || isProof) && <PasswordField id="auth-password" label={isProof ? "New password" : "Password"} autoComplete={isProof ? "new-password" : "current-password"} describedBy={isProof ? "password-guidance auth-feedback" : "auth-feedback"} disabled={busy} inputRef={password} />}
      {isProof && <><PasswordField id="auth-password-confirm" label="Confirm new password" autoComplete="new-password" describedBy="password-guidance auth-feedback" disabled={busy} inputRef={confirmation} /><p id="password-guidance" className="auth-note">Use 15–128 characters and a unique password. Password managers and paste are supported. Common or compromised passwords are not accepted.</p></>}
      {isSignIn && <div className="auth-recovery"><LocalLink to="/forgot-password" onNavigate={onNavigate}>Forgot password?</LocalLink></div>}
      <div id="auth-feedback" className="auth-feedback" aria-live="polite" aria-atomic="true">
        {error && <p className="auth-error" role="alert" data-testid="password-auth-error">{error.code === "local_policy" ? error.message : passwordFailureMessage(error, { proof: isProof })}</p>}
        {(unavailable || disabledByPolicy) && <p className="auth-note">Email and password access is currently unavailable. {isSignIn ? "You can continue with Google below." : "Please try again later."}</p>}
        {retrySeconds > 0 && <p className="auth-note">You can try again in {retrySeconds} {retrySeconds === 1 ? "second" : "seconds"}.</p>}
      </div>
      <button className="auth-primary" type="submit" disabled={disabled} data-testid="password-auth-submit">{busy ? (isSignIn ? "Signing in…" : "Please wait…") : isSignIn ? "Sign in" : isRegistration ? "Send verification link" : isRequest ? "Send reset link" : isVerification ? "Verify email and create password" : "Update password"}</button>
      {unavailable && <button className="auth-link" type="button" disabled={busy} onClick={() => { setUnavailable(false); setError(null); }}>Try this account action again</button>}
    </form>}
    {signingOut && <p className="auth-note" role="status">Please wait a moment.</p>}
    {logoutFailed && <button className="auth-primary" type="button" onClick={() => void auth.logout()} data-testid="signout-retry">Try signing out again</button>}
    {identityUnavailable && <button className="auth-primary" type="button" onClick={() => void auth.refresh()}>Check connection again</button>}
    {!accountLocked && (isSignIn || isRegistration) && <><div className="auth-divider"><span>or</span></div><GoogleSignInButton auth={auth} disabled={pending || auth.passwordPending} /></>}
    {!accountLocked && isSignIn && <p className="auth-account-link">New to AQUA? <LocalLink to="/register" onNavigate={onNavigate}>Create an account</LocalLink></p>}
    {isRegistration && <LocalLink to="/signin" onNavigate={onNavigate}>Already have an account? Sign in</LocalLink>}
    {isRequest && <LocalLink to="/signin" onNavigate={onNavigate}>Back to sign in</LocalLink>}
    {(path === "/check-email" || path === "/registration-sent") && <><p className="auth-note">Check your spam folder too. If no email arrives, wait at least five minutes before requesting another link. Delivery depends on account eligibility and sending limits.</p><LocalLink to="/signin" onNavigate={onNavigate} className="auth-primary">Back to sign in</LocalLink><LocalLink to={path === "/check-email" ? "/forgot-password" : "/register"} onNavigate={onNavigate}>Request another email</LocalLink></>}
    {invalidProof && !complete && <LocalLink to={isVerification ? "/register" : "/forgot-password"} onNavigate={onNavigate} className="auth-primary">Request a new {isVerification ? "verification" : "reset"} link</LocalLink>}
    {(complete || invalidProof) && <LocalLink to="/signin" onNavigate={onNavigate} className={complete ? "auth-primary" : "auth-link"}>Back to sign in</LocalLink>}
    {isProof && !complete && !invalidProof && <LocalLink to="/signin" onNavigate={onNavigate}>Back to sign in</LocalLink>}
    <Policies onNavigate={onNavigate} />
  </section>;
}

export default function AuthPage({ path = "/signin", proof = null, onNavigate, onProofConsumed, auth }) {
  return <main className="auth-page" data-testid="signin-page" aria-label="AQUA account access">
    <OpalBackdrop />
    <header className="auth-brand"><img src={mark} alt="" width="32" height="32" /><span>AQUA</span></header>
    <div className="auth-page__body"><aside className="auth-introduction" aria-label="Your financial workspace">
      <span className="auth-introduction__badge">Your financial workspace</span><h2>Financial answers.<br />A clearer perspective.</h2><p>Ask questions, explore patterns, and bring your data into focus. One calm space for your daily work.</p>
      <ul><li><img src={chat} alt="" width="18" height="18" />Start with a question in plain language</li><li><img src={chart} alt="" width="18" height="18" />Explore answers with charts and tables</li><li><img src={clock} alt="" width="18" height="18" />A focused workspace for your daily analysis</li></ul>
    </aside><AuthContent key={path} {...{ path, proof, onNavigate, onProofConsumed, auth }} /></div>
    <footer className="auth-page__footer"><span>AQUA</span><span>AQUA · Opal workspace</span></footer>
  </main>;
}
