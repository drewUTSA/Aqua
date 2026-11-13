import React from "react";
import { usePreferences } from "./PreferencesProvider.jsx";
import { useDataDeletion } from "./DataDeletionProvider.jsx";
export default function PrivacyDeletions({ auth }) {
  const preferences = usePreferences(), deletion = useDataDeletion();
  if (!auth || auth.demoMode || !auth.user?.id) return <p>Sign in to review personal data deletion.</p>;
  const capable = preferences.capabilities?.private_data_delete === true;
  const active = auth.status === "authenticated" && preferences.ready && !preferences.loading && !preferences.needsReload && capable && !!deletion && !deletion.busy;
  return <section className="privacy-export-panel" data-private-deletions><h3>Delete personal data</h3>
    <p>Review saved history deletion or permanent account deletion. Each action requires fresh verification and a typed confirmation.</p>
    {capable ? <div className="export-actions"><button type="button" data-delete-private-history disabled={!active} onClick={() => deletion.open("chat_history_v1")}>Delete saved history</button><button type="button" data-delete-private-account disabled={!active} onClick={() => deletion.open("account_v1")}>Delete account</button></div> : <p>Personal data deletion is currently unavailable.</p>}
    <p>A preference reset does not delete data or revoke sessions.</p>
  </section>;
}
