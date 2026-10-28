import React from "react";
import PreferenceDialog from "../../settings/PreferenceDialog.jsx";
import WorkspaceLibrary from "./WorkspaceLibrary.jsx";

export default function PromptLibraryDialog({ chat, suggestions, onPrompt, onClose }) {
  return <PreferenceDialog title="Saved prompts" onClose={onClose} className="prompt-library-dialog">
    {chat.durable && <WorkspaceLibrary chat={chat} onPrompt={onPrompt} section="prompts" />}
    {suggestions !== false && <section aria-label="Starter questions"><h3>Starter questions</h3>
      <p>Choose a starting point, then make it your own.</p>
      {chat.faqs.map((item) => <button type="button" key={item.id} onClick={() => onPrompt(item.prompt)}>{item.title}</button>)}
      {!chat.faqs.length && <p>No starter questions available.</p>}
    </section>}
    <button type="button" className="prompt-library-close" aria-label="Close saved prompts" onClick={onClose}>Done</button>
  </PreferenceDialog>;
}
