import React from "react";
import { assertHistory } from "../../services/historyAuthority.js";
import { resultBinding } from "./binding.js";
import { canApplyResultDraft } from "./apply.js";
import ResultCompanionDialog from "./ResultCompanionDialog.jsx";
import PreferenceDialog from "../../settings/PreferenceDialog.jsx";

export default function ResultCompanionHost({ reference, scope, chat, auth, onClose, onApplied }) {
  const binding = resultBinding(chat, auth.user?.id, reference.messageId, auth.session?.can_query === true && !auth.demoMode);
  if (!binding || binding.token !== reference.token) return <PreferenceDialog title="Result companion unavailable" onClose={onClose}>
    <p role="alert">This saved result is unavailable. Its original answer and composer remain available.</p>
    <button type="button" onClick={onClose}>Close result companion</button></PreferenceDialog>;
  const apply = (value, expected) => {
    try { assertHistory(scope?.history); } catch { return false; }
    if (!canApplyResultDraft({ scope, binding, ownerId: auth.user?.id, csrfToken: auth.csrfToken, canQuery: auth.canQuery,
      archived: chat.active?.archived, draft: chat.draft, expected, value })) return false;
    chat.setDraft(value); onClose(); onApplied(); return true;
  };
  return <ResultCompanionDialog binding={binding} csrfToken={auth.csrfToken} historyContext={scope?.history} draft={scope?.draft ?? chat.draft}
    canApply={auth.canQuery && !chat.active?.archived} onApply={apply} onClose={onClose} onAuthFailure={auth.refresh} />;
}
