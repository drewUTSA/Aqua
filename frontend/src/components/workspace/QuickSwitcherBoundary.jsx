import React from "react";
import PreferenceDialog from "../../settings/PreferenceDialog.jsx";

// Contain optional downloads without unmounting the account's chat or draft.
export default class QuickSwitcherBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (!this.state.failed) return this.props.children;
    if (this.props.kind === "settings") return <section className="workspace-notice" aria-label="Settings unavailable">
      <h2>Settings unavailable</h2><p role="alert">Settings could not open. Your conversation and unsent text are still available.</p>
      <button type="button" autoFocus onClick={this.props.onClose}>Back to workspace</button>
    </section>;
    const prompts = this.props.kind === "prompts";
    return <PreferenceDialog title={this.props.title || (prompts ? "Saved prompts unavailable" : "Shortcuts unavailable")} onClose={this.props.onClose}>
      <p role="alert">{this.props.message || (prompts ? "Saved prompts could not open. Your conversation and unsent text are still available."
        : "Workspace shortcuts could not open. You can keep using the sidebar.")}</p>
      <button type="button" onClick={this.props.onClose}>{this.props.closeLabel || (prompts ? "Close saved prompts" : "Close shortcuts")}</button>
    </PreferenceDialog>;
  }
}

export function OptionalDialogLoading({ title, onClose, closeLabel }) {
  return <PreferenceDialog title={title} onClose={onClose}><p role="status">Opening optional toolsâ€¦</p>
    <button type="button" onClick={onClose}>{closeLabel}</button></PreferenceDialog>;
}
