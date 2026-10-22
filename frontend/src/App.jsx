import React, { useCallback, useEffect, useRef, useState } from "react";
import { useGoogleAuth } from "./hooks/useGoogleAuth.js";
import AuthPage from "./pages/AuthPage.jsx";
import LegalPage from "./pages/LegalPage.jsx";
import Workspace from "./components/workspace/Workspace.jsx";
import { AUTH_PATHS, consumeLocation, navigateLocal } from "./services/routes.js";

// Capture once before UI/SDK setup, including StrictMode's initializer replay.
const initialRoute = typeof window === "undefined" ? { path: "/", proof: null }
  : consumeLocation(window.location, window.history);
export default function App() {
  const [route, setRoute] = useState(() => ({ ...initialRoute, revision: 0 }));
  const acceptRoute = useCallback((next) => setRoute((current) => ({ ...next, revision: current.revision + 1 })), []);
  const navigate = useCallback((path) => navigateLocal(path, window.history, acceptRoute), [acceptRoute]);
  useEffect(() => {
    const sync = (event) => {
      // Fragment navigation may queue both popstate and hashchange. The first
      // captures and strips its bearer; the empty second event must not erase it.
      if (event.type === "hashchange" && !window.location.hash) return;
      acceptRoute(consumeLocation(window.location, window.history));
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("hashchange", sync);
    initialRoute.proof = null;
    return () => { window.removeEventListener("popstate", sync); window.removeEventListener("hashchange", sync); };
  }, [acceptRoute]);
  const legal = ["/privacy", "/terms"].includes(route.path);
  const accountStarted = useRef(!legal);
  if (!legal) accountStarted.current = true;
  // Direct policy visits need no sign-in bootstrap. Once started, the account
  // owner must survive policy navigation, including an unresolved logout.
  if (!accountStarted.current) return <LegalPage kind={route.path.slice(1)} onNavigate={navigate} />;
  return <AccountApp route={route} navigate={navigate}
    clearProof={() => setRoute((current) => ({ ...current, proof: null }))} />;
}
function AccountApp({ route, navigate, clearProof }) {
  const auth = useGoogleAuth();
  const unlocked = auth.demoMode || auth.status === "authenticated";
  const accountId = auth.demoMode ? "demo" : auth.user?.id ?? null;
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
    {retain && <Workspace key={accountId} auth={auth} path={route.path} onNavigate={navigate} hidden={!unlocked || !workspaceRoute} />}
    {legal ? <LegalPage kind={route.path.slice(1)} onNavigate={navigate} /> : (!unlocked || !workspaceRoute) && (AUTH_PATHS.has(route.path) || workspaceRoute
      ? <AuthPage key={`${route.path}:${route.revision}`} path={workspaceRoute ? "/signin" : route.path} proof={route.proof}
          onProofConsumed={clearProof} onNavigate={navigate} auth={auth} />
      : <main className="not-found"><h1 tabIndex={-1}>Page not found</h1><p>This page is not available.</p>
          <button type="button" onClick={() => navigate(unlocked ? "/" : "/signin")}>Back to AQUA</button></main>)}
  </>;
}
