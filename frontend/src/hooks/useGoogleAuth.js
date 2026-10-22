import { useCallback, useEffect, useRef, useState } from "react";
import { AuthError, fetchAuthConfig, fetchSession, signInWithGoogle, signOut } from "../services/authClient.js";
import { disableGoogleAutoSelect } from "../services/googleIdentity.js";
import { DEMO_MODE } from "../services/runtimeConfig.js";
import { PasswordAuthError, signInWithPassword } from "../services/passwordAuthClient.js";

const initialState = { status: "loading", session: null, config: null, error: "", googleError: "", passwordError: null, signInMethod: null };
const googleUnavailable = "Google sign-in is temporarily unavailable. You can still use your AQUA password.";

async function googleConfig(signal) {
  try { return { config: await fetchAuthConfig({ signal }), googleError: "" }; }
  catch (error) {
    if (error?.name === "AbortError") throw error;
    // Provider availability cannot turn off the independent password method.
    return { config: null, googleError: googleUnavailable };
  }
}

export function useGoogleAuth({ demoMode = DEMO_MODE } = {}) {
  const [state, setState] = useState(() => demoMode ? { ...initialState, status: "demo" } : initialState);
  const stateRef = useRef(state);
  const active = useRef(null);
  const mounted = useRef(false);
  const channel = useRef(null);
  const notify = (type = "changed") => channel.current?.postMessage({ type });
  const replace = useCallback((next) => {
    if (!mounted.current) return;
    stateRef.current = next;
    setState(next);
  }, []);
  const begin = useCallback(() => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    return controller;
  }, []);
  const isCurrent = (controller) => mounted.current && active.current === controller && !controller.signal.aborted;

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
      confirmedSession = session;
      // Password login can start as soon as the session is known to be absent;
      // a slow or broken Google config request must not hold that form hostage.
      if (!session && isCurrent(controller)) replace({ ...initialState, status: "signedout" });
      const google = session ? { config: null, googleError: "" } : await googleConfig(controller.signal);
      if (isCurrent(controller)) replace({ ...initialState, status: session ? "authenticated" : "signedout", session, ...google });
    } catch (error) {
      if (isCurrent(controller)) replace({ ...initialState, session: confirmedSession, status: "unavailable", error: error.message });
    }
  }, [begin, demoMode, replace]);

  useEffect(() => {
    mounted.current = true;
    if (!demoMode) void refresh();
    return () => { mounted.current = false; active.current?.abort(); };
  }, [demoMode, refresh]);

  const acceptCredential = useCallback(async (credential) => {
    const current = stateRef.current;
    if (demoMode || current.status !== "signedout" || !current.config || current.config.capabilities?.google_login === false) return;
    const controller = begin();
    replace({ ...current, status: "signingin", signInMethod: "google", error: "", passwordError: null });
    try {
      const session = await signInWithGoogle({ credential, csrfToken: current.config.csrf_token, signal: controller.signal });
      if (isCurrent(controller)) { replace({ ...initialState, status: "authenticated", session }); notify(); }
    } catch (error) {
      if (!isCurrent(controller)) return;
      replace({ ...initialState, status: "signedout", error: error.message, googleError: error.message });
      try {
        const google = await googleConfig(controller.signal);
        if (isCurrent(controller)) replace({ ...initialState, status: "signedout", ...google, error: error.message, googleError: error.message });
      } catch (configError) {
        if (isCurrent(controller)) replace({ ...initialState, status: "unavailable", error: configError.message });
      }
    }
  }, [begin, demoMode, replace]);

  const authenticatePassword = useCallback(async (email, password) => {
    const current = stateRef.current;
    if (demoMode || current.status !== "signedout") return false;
    const controller = begin();
    replace({ ...current, status: "signingin", signInMethod: "password", error: "", passwordError: null });
    try {
      const session = await signInWithPassword({ email, password, signal: controller.signal });
      if (!isCurrent(controller)) return false;
      replace({ ...initialState, status: "authenticated", session });
      notify();
      return true;
    } catch (error) {
      if (!isCurrent(controller)) return false;
      const safe = error instanceof PasswordAuthError ? error : new PasswordAuthError(503, "unavailable");
      replace({ ...current, status: "signedout", signInMethod: null, error: safe.message, passwordError: safe,
        googleError: current.config ? current.googleError : current.googleError || googleUnavailable });
      return false;
    }
  }, [begin, demoMode, replace]);

  const logout = useCallback(async () => {
    const current = stateRef.current;
    if (demoMode || !["authenticated", "logoutfailed"].includes(current.status)) return;
    const controller = begin();
    replace({ ...current, status: "signingout", error: "" });
    try {
      await signOut({ csrfToken: current.session.csrf_token, signal: controller.signal });
    } catch (error) {
      if (!isCurrent(controller)) return;
      if (!(error instanceof AuthError && error.status === 401)) {
        replace({ ...current, status: "logoutfailed", error: "AQUA couldn't confirm sign-out. Your workspace is locked. Please try again." });
        return;
      }
    }
    if (!isCurrent(controller)) return;
    disableGoogleAutoSelect();
    replace({ ...initialState, status: "signedout" });
    notify();
    try {
      const google = await googleConfig(controller.signal);
      if (isCurrent(controller)) replace({ ...initialState, status: "signedout", ...google });
    } catch (error) {
      if (isCurrent(controller)) replace({ ...initialState, status: "unavailable", error: error.message });
    }
  }, [begin, demoMode, replace]);

  const sessionEnded = useCallback(() => {
    // Reset may commit even if its response is lost. Lock cached identities at
    // the start of the attempt; never replay it or restore stale cached access.
    const controller = begin();
    disableGoogleAutoSelect();
    replace({ ...initialState, status: "signedout" });
    notify("locked");
    void googleConfig(controller.signal).then((google) => {
      if (isCurrent(controller)) replace({ ...initialState, status: "signedout", ...google });
    }).catch(() => {});
  }, [begin, replace]);

  useEffect(() => {
    if (demoMode) return undefined;
    const lock = () => {
      if (["signingout", "logoutfailed"].includes(stateRef.current.status)) return;
      const controller = begin();
      replace({ ...initialState, status: "signedout" });
      void googleConfig(controller.signal).then((google) => {
        if (isCurrent(controller)) replace({ ...initialState, status: "signedout", ...google });
      }).catch(() => {});
    };
    // Only metadata crosses tabs. Never broadcast identity, bearer or CSRF.
    const events = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel("aqua-session-events");
    channel.current = events;
    if (events) events.onmessage = ({ data }) => {
      if (data?.type === "changed") void refresh({ sessionChanged: true });
      if (data?.type === "locked") lock();
    };
    let checked = Date.now();
    const foreground = () => {
      if (document.visibilityState !== "visible" || Date.now() - checked < 10000) return;
      checked = Date.now();
      void refresh();
    };
    window.addEventListener("focus", foreground);
    document.addEventListener("visibilitychange", foreground);
    return () => {
      if (channel.current === events) channel.current = null;
      events?.close();
      window.removeEventListener("focus", foreground);
      document.removeEventListener("visibilitychange", foreground);
    };
  }, [begin, demoMode, refresh, replace]);

  return {
    ...state, demoMode, refresh, logout, acceptCredential, authenticatePassword, sessionEnded,
    passwordPending: state.status === "signingin" && state.signInMethod === "password",
    user: state.session?.user ?? null,
    csrfToken: state.session?.csrf_token ?? "",
    canQuery: demoMode || (state.status === "authenticated" && state.session?.can_query === true)
  };
}
