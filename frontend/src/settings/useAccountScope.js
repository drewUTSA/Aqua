import { useLayoutEffect, useRef } from "react";
import { createAccountRequestScope } from "./accountState.js";

export default function useAccountScope(auth) {
  const identity = useRef(null);
  identity.current = { owner: auth.user?.id, csrfToken: auth.csrfToken, active: auth.status === "authenticated" && !auth.demoMode };
  const scope = useRef(null);
  if (!scope.current) scope.current = createAccountRequestScope(auth.user.id, () => identity.current);
  useLayoutEffect(() => { scope.current.activate(); return () => scope.current.dispose(); }, []);
  useLayoutEffect(() => { if (!identity.current.active) scope.current.abort(); }, [auth.status, auth.demoMode]);
  return scope.current;
}
