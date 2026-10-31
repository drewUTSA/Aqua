import { useLayoutEffect, useRef } from "react";
import { createAccountRequestScope } from "./accountState.js";

export default function useAccountScope(auth) {
  const identity = useRef(null);
  identity.current = { owner: auth.user?.id, csrfToken: auth.csrfToken, active: auth.status === "authenticated" && !auth.demoMode };
  const scope = useRef(null);
  if (!scope.current) scope.current = createAccountRequestScope(auth.user.id, () => identity.current);
  useLayoutEffect(() => { scope.current.activate(); return () => scope.current.dispose(); }, []);
  // End the old generation permanently, including an A → B → A CSRF change.
  // The per-request synchronous checks hide authority during render; this
  // abort prevents a later matching token from reviving an earlier request.
  useLayoutEffect(() => { scope.current.abort(); }, [auth.status, auth.demoMode, auth.csrfToken, auth.user?.id]);
  return scope.current;
}
