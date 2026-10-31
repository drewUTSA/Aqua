import React, { useCallback, useEffect, useRef, useState } from "react";
import { useGoogleAuth } from "./hooks/useGoogleAuth.js";
import AuthPage from "./pages/AuthPage.jsx";
import LegalPage from "./pages/LegalPage.jsx";
import Workspace from "./components/workspace/Workspace.jsx";
import { AUTH_PATHS, ACCOUNT_ACTION_PATHS, consumeLocation, navigateLocal } from "./services/routes.js";
import AccountActionLanding from "./pages/AccountActionLanding.jsx";
import NotificationProvider from "./settings/NotificationProvider.jsx";
import { PreferencesProvider } from "./settings/PreferencesProvider.jsx";
import { purgeDevicePreferences } from "./settings/deviceStore.js";

// Capture once before UI/SDK setup, including StrictMode's initializer replay.
const initialRoute = typeof window === "undefined" ? { path: "/", proof: null }
  : consumeLocation(window.location, window.history);
export default function App() {
  const [route, setRoute] = useState(() => ({ ...initialRoute, revision: 0 }));
  const guard = useRef(null), currentRoute = useRef(route);
  currentRoute.current = route;
  const registerGuard = useCallback((value) => { guard.current = value; }, []);
  const acceptRoute = useCallback((next) => setRoute((current) => ({ ...next, revision: current.revision + 1 })), []);
  const navigate = useCallback((path) => {
    const proceed = () => navigateLocal(path, window.history, acceptRoute);
    if (guard.current) void guard.current(proceed); else proceed();
  }, [acceptRoute]);
  useEffect(() => {
    const sync = (event) => {
      // Fragment navigation may queue both popstate and hashchange. The first
      // captures and strips its bearer; the empty second event must not erase it.
      if (event.type === "hashchange" && !window.location.hash) return;
      const next = consumeLocation(window.location, window.history);
      if (guard.current && currentRoute.current.path === "/settings" && next.path !== "/settings") {
        // Back already moved browser history. Restore the visible draft route
        // while asking; Keep editing must leave URL and mounted state aligned.
        window.history.replaceState(null, "", "/settings");
        void guard.current(() => navigateLocal(next.path, window.history, acceptRoute));
      } else acceptRoute(next);
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("hashchange", sync);
    initialRoute.proof = null;
    return () => { window.removeEventListener("popstate", sync); window.removeEventListener("hashchange", sync); };
  }, [acceptRoute]);
  const legal = ["/privacy", "/terms"].includes(route.path);
  const accountStarted = useRef(!legal);
  if (!legal) accountStarted.current = true;
  // consumeLocation already scrubbed the fragment before React or any SDK.
  // A mail landing never receives a bearer or bootstraps an account mutation.
  if (ACCOUNT_ACTION_PATHS.has(route.path)) return <AccountActionLanding onNavigate={navigate} />;
  // Direct policy visits need no sign-in bootstrap. Once started, the account
  // owner must survive policy navigation, including an unresolved logout.
  if (!accountStarted.current) return <LegalPage kind={route.path.slice(1)} onNavigate={navigate} />;
  return <AccountApp route={route} navigate={navigate} registerGuard={registerGuard}
    clearProof={() => setRoute((current) => ({ ...current, proof: null }))} />;
}
function AccountApp({ route, navigate, clearProof, registerGuard }) {
  const auth = useGoogleAuth();
  const unlocked = auth.demoMode || auth.status === "authenticated";
  const accountId = auth.demoMode ? "demo" : auth.user?.id ?? null;
  const previousAccount = useRef(accountId);
  useEffect(() => {
    if (previousAccount.current && previousAccount.current !== accountId) purgeDevicePreferences(previousAccount.current);
    previousAccount.current = accountId;
  }, [accountId]);
  const owner = useRef(null);
  if (owner.current !== accountId) owner.current = null;
  if (unlocked) owner.current = accountId;
  const retain = accountId !== null && owner.current === accountId;
  const workspaceRoute = route.path === "/" || route.path === "/settings";
  const legal = ["/privacy", "/terms"].includes(route.path);
  useEffect(() => {
    if (unlocked && route.path === "/signin") navigate("/");
    else if (auth.status === "signedout" && workspaceRoute) navigate("/signin");
  }, [auth.status, unlocked, route.path, workspaceRoute, navigate]);
  // Account UI and dataset permission are separate. Pending/failed logout keeps
  // this account mounted but hidden/inert; confirmed logout or switch clears it.
  return <>
    {retain && <PreferencesProvider key={accountId} auth={auth} previewEnabled={route.path === "/settings"} registerGuard={registerGuard}>
      <NotificationProvider auth={auth}>
      <Workspace auth={auth} path={route.path} onNavigate={navigate} hidden={!unlocked || !workspaceRoute} />
      </NotificationProvider>
    </PreferencesProvider>}
    {legal ? <LegalPage kind={route.path.slice(1)} onNavigate={navigate} /> : (!unlocked || !workspaceRoute) && (AUTH_PATHS.has(route.path) || workspaceRoute
      ? <AuthPage key={`${route.path}:${route.revision}`} path={workspaceRoute ? "/signin" : route.path} proof={route.proof}
          onProofConsumed={clearProof} onNavigate={navigate} auth={auth} />
      : <main className="not-found"><h1 tabIndex={-1}>Page not found</h1><p>This page is not available.</p>
          <button type="button" onClick={() => navigate(unlocked ? "/" : "/signin")}>Back to AQUA</button></main>)}
  </>;
}
