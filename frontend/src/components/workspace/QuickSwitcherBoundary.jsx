import React from "react";
import PreferenceDialog from "../../settings/PreferenceDialog.jsx";

// A failed optional download must not unmount the account's chat or draft.
export default class QuickSwitcherBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <PreferenceDialog title="Shortcuts unavailable" onClose={this.props.onClose}>
      <p role="alert">Workspace shortcuts could not open. You can keep using the sidebar.</p>
      <button type="button" onClick={this.props.onClose}>Close shortcuts</button>
    </PreferenceDialog> : this.props.children;
  }
}
