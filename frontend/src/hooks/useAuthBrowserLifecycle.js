import { useEffect } from "react";
import { clearHistory } from "../services/historyAuthority.js";
import { attachAuthBrowserEvents } from "../services/authBrowserEvents.js";
import { googleConfig } from "../services/authProviderConfig.js";

export function useAuthBrowserLifecycle({ initialState, demoMode, stateRef, begin, replace, finish, isCurrent, refresh, channel, cancelDeadline, active }) {
  useEffect(() => {
    if (demoMode) return undefined;
    const lock = () => {
      if (["signingout", "logoutfailed"].includes(stateRef.current.status)) return;
      const controller = begin();
      clearHistory();
      replace({ ...initialState, status: "signedout" });
      finish(controller);
      void googleConfig(controller.signal).then((google) => {
        if (isCurrent(controller)) replace({ ...initialState, status: "signedout", ...google });
      }).catch(() => {});
    };
    const events = attachAuthBrowserEvents({
      onRefresh: (options) => void refresh(options), onLock: lock,
      canRefresh: () => !["signedout", "signingin", "signingout", "logoutfailed"].includes(stateRef.current.status),
      onOffline: () => {
        const current = stateRef.current;
        if (["signingout", "logoutfailed"].includes(current.status)) return;
        cancelDeadline.current(); active.current?.abort();
        replace({ ...current, status: "unavailable", error: "You appear to be offline. Reconnect, then check your sign-in again." });
      }
    });
    channel.current = events;
    return () => {
      if (channel.current === events) channel.current = null;
      events.dispose();
    };
  }, [initialState, begin, demoMode, refresh, replace, finish, isCurrent, stateRef, channel, cancelDeadline, active]);

}
