import React, { lazy, Suspense, useState } from "react";

function WorkspaceUnavailable({ hidden, retry, auth }) {
  if (hidden) return null;
  return <main className="auth-card" aria-labelledby="workspace-load-heading">
    <h1 id="workspace-load-heading">Workspace unavailable</h1>
    <p role="alert">AQUA couldn't load your workspace. Check your connection and try again.</p>
    <button type="button" onClick={retry}>Try again</button>
    <button type="button" onClick={() => window.location.reload()}>Reload page</button>
    {!auth.demoMode && <button type="button" onClick={auth.logout}>Sign out</button>}
  </main>;
}

function workspaceView() {
  return lazy(() => import(/* webpackChunkName: "Workspace" */ "./Workspace.jsx")
    .catch(() => ({ default: WorkspaceUnavailable })));
}

export default function WorkspaceEntry(props) {
  const [View, setView] = useState(workspaceView);
  // A new lazy component retries a failed download. Successful imports retain
  // the mounted workspace while the parent hides it for legal pages or logout.
  return <Suspense fallback={props.hidden ? null : <p role="status">Opening your workspace…</p>}>
    <View {...props} retry={() => setView(workspaceView)} />
  </Suspense>;
}
