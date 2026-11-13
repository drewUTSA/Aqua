import { useChat } from "../../hooks/useChat.js";

// Production sign-in should not download the visit-local demo's seeded history.
export default function DemoWorkspace({ auth, children }) {
  const chat = useChat({ demoMode: auth.demoMode, canQuery: auth.canQuery, csrfToken: auth.csrfToken, onAuthFailure: auth.refresh });
  return children(chat);
}
