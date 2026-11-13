import { useCallback, useEffect, useRef, useState } from "react";
import { AuthError, fetchSession, signInWithGoogle, signOut } from "../services/authClient.js";
import { disableGoogleAutoSelect } from "../services/googleIdentity.js";
import { DEMO_MODE } from "../services/runtimeConfig.js";
import { PasswordAuthError, signInWithPassword } from "../services/passwordAuthClient.js";
import { activateSession, clearHistory, subscribeHistory } from "../services/historyAuthority.js";
import { authDeadline } from "../services/authBrowserEvents.js";
import { googleConfig, googleUnavailable } from "../services/authProviderConfig.js";
import { useAuthBrowserLifecycle } from "./useAuthBrowserLifecycle.js";

const initialState = { status: "loading", session: null, config: null, error: "", googleError: "", passwordError: null, signInMethod: null };

const cookieUnavailable = "AQUA couldn't confirm your sign-in session. Check that cookies are allowed for this site, then check your connection again.";

async function confirmBrowserSession(accepted, signal) {
  const session = await fetchSession({ signal });
  if (!session || session.user.id !== accepted.user.id) throw new AuthError(503, cookieUnavailable);
  return session;
}

export function useGoogleAuth({ demoMode = DEMO_MODE } = {}) {
  const [state, setState] = useState(() => demoMode ? { ...initialState, status: "demo" } : initialState);
  const [historyEpoch, setHistoryEpoch] = useState(0);
  const stateRef = useRef(state);
  const active = useRef(null);
  const cancelDeadline = useRef(() => {});
  const mounted = useRef(false);
  const channel = useRef(null);
  const sessionMayRemain = useRef(false);
  const notify = (type = "changed") => channel.current?.notify(type);
  const replace = useCallback((next) => {
    if (!mounted.current) return;
    stateRef.current = next;
    setState(next);
  }, []);
  const begin = useCallback(() => {
    cancelDeadline.current();
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    cancelDeadline.current = authDeadline(controller, () => mounted.current && active.current === controller, () => {
      const current = stateRef.current;
      const loggingOut = ["signingout", "logoutfailed"].includes(current.status);
      replace({ ...current, status: loggingOut ? "logoutfailed" : "unavailable",
        error: loggingOut ? "AQUA couldn't confirm sign-out. Your workspace is locked. Please try again."
          : "AQUA couldn't check your sign-in connection. Please try again." });
    });
    return controller;
  }, [replace]);
  const finish = useCallback((controller) => { if (active.current === controller) cancelDeadline.current(); }, []);
  const isCurrent = useCallback((controller) => mounted.current && active.current === controller && !controller.signal.aborted, []);

  const refresh = useCallback(async ({ sessionChanged = false } = {}) => {
    if (demoMode) return;
    const current = stateRef.current;
    // A query finishing during logout must not cancel revocation or unlock the
    // account after a failed attempt. Only an explicit logout retry resumes it.
    if (["signingout", "logoutfailed"].includes(current.status) || (current.status === "signingin" && !sessionChanged)) return;
    const controller = begin();
    replace({ ...initialState, session: current.session, status: "loading" });
    let confirmedSession = current.session;
    try {
      const session = await fetchSession({ signal: controller.signal });
      if (!isCurrent(controller)) return;
      if (session) setHistoryEpoch(activateSession(session));
      confirmedSession = session;
      finish(controller);
      // Password login can start as soon as the session is known to be absent;
      // a slow or broken Google config request must not hold that form hostage.
      if (!session && isCurrent(controller)) { sessionMayRemain.current = false; clearHistory(); replace({ ...initialState, status: "signedout" }); }
      const google = session ? { config: null, googleError: "" } : await googleConfig(controller.signal);
      if (isCurrent(controller)) replace({ ...initialState, status: session ? "authenticated" : "signedout", session, ...google });
    } catch (error) {
      if (isCurrent(controller)) replace({ ...initialState, session: confirmedSession, status: "unavailable", error: error.message });
    } finally { finish(controller); }
  }, [begin, demoMode, replace, finish, isCurrent]);

  useEffect(() => subscribeHistory(context => {
    setHistoryEpoch(context.sequence);
    // Every private subtree remounts before new work is enabled. Refresh is
    // authoritative; old prompts and responses are never replayed by this path.
    void refresh();
  }), [refresh]);

  useEffect(() => {
    mounted.current = true;
    if (!demoMode) void refresh();
    return () => { mounted.current = false; cancelDeadline.current(); active.current?.abort(); };
  }, [demoMode, refresh]);

  const acceptCredential = useCallback(async (credential) => {
    const current = stateRef.current;
    if (demoMode || current.status !== "signedout" || !current.config || current.config.capabilities?.google_login === false) return;
    const controller = begin();
    replace({ ...current, status: "signingin", signInMethod: "google", error: "", passwordError: null });
    let accepted = false;
    try {
      const response = await signInWithGoogle({ credential, csrfToken: current.config.csrf_token, signal: controller.signal });
      accepted = true;
      if (!isCurrent(controller)) return;
      const session = await confirmBrowserSession(response, controller.signal);
      if (isCurrent(controller)) { setHistoryEpoch(activateSession(session)); replace({ ...initialState, status: "authenticated", session }); notify(); }
    } catch (error) {
      if (!isCurrent(controller)) return;
      if (accepted) { replace({ ...initialState, status: "unavailable", error: cookieUnavailable }); return; }
      replace({ ...initialState, status: "signedout", error: error.message, googleError: error.message });
      finish(controller);
      try {
        const google = await googleConfig(controller.signal);
        if (isCurrent(controller)) replace({ ...initialState, status: "signedout", ...google, error: error.message, googleError: error.message });
      } catch (configError) {
        if (isCurrent(controller)) replace({ ...initialState, status: "unavailable", error: configError.message });
      }
    } finally { finish(controller); }
  }, [begin, demoMode, replace, finish, isCurrent]);

  const authenticatePassword = useCallback(async (email, password) => {
    const current = stateRef.current;
    if (demoMode || current.status !== "signedout") return false;
    const controller = begin();
    replace({ ...current, status: "signingin", signInMethod: "password", error: "", passwordError: null });
    let accepted = false;
    try {
      const response = await signInWithPassword({ email, password, signal: controller.signal });
      accepted = true;
      if (!isCurrent(controller)) return false;
      const session = await confirmBrowserSession(response, controller.signal);
      if (!isCurrent(controller)) return false;
      setHistoryEpoch(activateSession(session));
      replace({ ...initialState, status: "authenticated", session });
      notify();
      return true;
    } catch (error) {
      if (!isCurrent(controller)) return false;
      if (accepted) { replace({ ...initialState, status: "unavailable", error: cookieUnavailable }); return false; }
      const safe = error instanceof PasswordAuthError ? error : new PasswordAuthError(503, "unavailable");
      replace({ ...current, status: "signedout", signInMethod: null, error: safe.message, passwordError: safe,
        googleError: current.config ? current.googleError : current.googleError || googleUnavailable });
      return false;
    } finally { finish(controller); }
  }, [begin, demoMode, replace, finish, isCurrent]);

  const logout = useCallback(async () => {
    const current = stateRef.current;
    if (demoMode || !["authenticated", "logoutfailed"].includes(current.status)) return;
    const controller = begin();
    replace({ ...current, status: "signingout", error: "" });
    try {
      await signOut({ csrfToken: current.session.csrf_token, signal: controller.signal });
    } catch (error) {
      if (!isCurrent(controller)) { finish(controller); return; }
      if (!(error instanceof AuthError && error.status === 401)) {
        finish(controller);
        replace({ ...current, status: "logoutfailed", error: "AQUA couldn't confirm sign-out. Your workspace is locked. Please try again." });
        return;
      }
    }
    if (!isCurrent(controller)) { finish(controller); return; }
    disableGoogleAutoSelect();
    sessionMayRemain.current = false;
    clearHistory();
    replace({ ...initialState, status: "signedout" });
    notify();
    finish(controller);
    try {
      const google = await googleConfig(controller.signal);
      if (isCurrent(controller)) replace({ ...initialState, status: "signedout", ...google });
    } catch (error) {
      if (isCurrent(controller)) replace({ ...initialState, status: "unavailable", error: error.message });
    } finally { finish(controller); }
  }, [begin, demoMode, replace, finish, isCurrent]);

  const sessionEnded = useCallback(() => {
    // Reset may commit even if its response is lost. Lock cached identities at
    // the start of the attempt; never replay it or restore stale cached access.
    const controller = begin();
    sessionMayRemain.current = true;
    disableGoogleAutoSelect();
    clearHistory();
    replace({ ...initialState, status: "signedout" });
    notify("locked");
    finish(controller);
    void googleConfig(controller.signal).then((google) => {
      if (isCurrent(controller)) replace({ ...initialState, status: "signedout", ...google });
    }).catch(() => {});
  }, [begin, replace, finish, isCurrent]);

  useAuthBrowserLifecycle({ initialState, demoMode, stateRef, sessionMayRemain, begin, replace, finish, isCurrent, refresh, channel, cancelDeadline, active });

  return {
    ...state, demoMode, historyEpoch, refresh, logout, acceptCredential, authenticatePassword, sessionEnded,
    passwordPending: state.status === "signingin" && state.signInMethod === "password",
    user: state.session?.user ?? null,
    csrfToken: state.session?.csrf_token ?? "",
    canQuery: demoMode || (state.status === "authenticated" && state.session?.can_query === true)
  };
}
