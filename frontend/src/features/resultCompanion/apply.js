import { boundedCompanionQuestion } from "../../services/companionClient.js";

// History is checked by Workspace immediately before this current-state fence.
export function canApplyResultDraft({ scope, binding, ownerId, csrfToken, canQuery, archived, draft, expected, value }) {
  try { boundedCompanionQuestion(value); } catch { return false; }
  return Boolean(scope && binding && expected && canQuery && !archived && scope.ownerId === ownerId && binding.ownerId === ownerId
    && scope.csrfToken === csrfToken && expected.token === binding.token && expected.token === scope.token
    && expected.draft === scope.draft && draft === scope.draft);
}
