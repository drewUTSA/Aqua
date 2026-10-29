// Account requests and name edits are separate from presentation preferences.
// No state in this module is persisted, exported or replayed automatically.
export function createAccountRequestScope(owner, currentIdentity) {
  let alive = true, generation = 0;
  const pending = new Map();
  const permitted = () => alive && currentIdentity()?.owner === owner && currentIdentity()?.active === true;
  const abort = () => {
    generation++;
    for (const controller of pending.values()) controller.abort();
    pending.clear();
  };
  return {
    activate() { alive = true; },
    begin(key) {
      if (!permitted()) return null;
      pending.get(key)?.abort();
      const controller = new AbortController(), issued = generation, csrfToken = currentIdentity()?.csrfToken;
      pending.set(key, controller);
      return {
        signal: controller.signal,
        current: () => permitted() && currentIdentity()?.csrfToken === csrfToken && generation === issued && pending.get(key) === controller && !controller.signal.aborted,
        finish: () => { if (pending.get(key) === controller) pending.delete(key); }
      };
    },
    abort,
    dispose() { alive = false; abort(); }
  };
}

export function nameEditor(profile) {
  return { base: profile, draft: profile.user.name, stage: "editing", error: "", latest: null, attempt: null, reason: "" };
}

export function acceptsAccountSnapshot(previous, next) {
  return !previous || next.user.id === previous.user.id && (next.revision > previous.revision
    || next.revision === previous.revision && next.user.name === previous.user.name);
}

const uncertain = "AQUA could not confirm whether your name was saved. Your edit is still here. Check the saved name before trying again.";
export function accountFailure(error, fallback = "Account details are unavailable. Try again when your connection is available.") {
  if (error?.status === 401) return "Your session has ended. Sign in again to review your account.";
  if (error?.status === 403) return "This account action is currently unavailable.";
  if (error?.status === 429) return "Too many account actions. Wait before trying again.";
  return fallback;
}

export function nameEditorReducer(state, action) {
  switch (action.type) {
    case "edit":
      if (["saving", "checking", "complete"].includes(state.stage)) return state;
      return { ...state, draft: action.value, error: state.stage === "editing" ? "" : state.error };
    case "invalid": return state.stage === "editing" ? { ...state, error: "Enter a name from 1 to 120 characters, without control or hidden formatting characters." } : state;
    case "save":
      if (state.stage !== "editing") return state;
      return { ...state, stage: "saving", error: "", attempt: { revision: state.base.revision, name: action.name, draft: state.draft } };
    case "saved": return state.stage === "saving" ? { ...state, stage: "complete", base: action.profile, draft: action.profile.user.name, error: "", latest: null } : state;
    case "failed": {
      if (state.stage !== "saving") return state;
      if (action.error?.status === 409) return { ...state, stage: "blocked", reason: "conflict", error: "Your account changed elsewhere. Reload the saved name and review your edit before saving." };
      if ([401, 403, 422, 429].includes(action.error?.status)) return { ...state, stage: "editing", error: action.error.status === 422
        ? "Check your name and try again. Your edit is still here." : accountFailure(action.error) };
      return { ...state, stage: "blocked", reason: "uncertain", error: uncertain };
    }
    case "check":
      if (!["blocked", "review"].includes(state.stage)) return state;
      return { ...state, stage: "checking", error: "" };
    case "checked": {
      if (state.stage !== "checking") return state;
      if (!acceptsAccountSnapshot(state.base, action.profile)) {
        return { ...state, stage: "blocked", latest: null, error: "AQUA could not confirm the saved account revision. Your edit is still here. Check the saved name again before saving." };
      }
      const confirmed = state.attempt && state.draft === state.attempt.draft && action.profile.revision >= state.attempt.revision && action.profile.user.name === state.attempt.name;
      return confirmed ? { ...state, stage: "complete", base: action.profile, draft: action.profile.user.name, latest: null, error: "" }
        : { ...state, stage: "review", latest: action.profile, error: "" };
    }
    case "check-failed": return state.stage === "checking" ? { ...state, stage: "blocked", error: accountFailure(action.error, "The saved name could not be checked. Your edit is still here. Try checking again before saving.") } : state;
    case "keep-edit":
    case "use-saved":
      if (state.stage !== "review" || !state.latest) return state;
      return { ...state, base: state.latest, draft: action.type === "use-saved" ? state.latest.user.name : state.draft,
        stage: "editing", error: "", latest: null, attempt: null, reason: "" };
    default: return state;
  }
}
