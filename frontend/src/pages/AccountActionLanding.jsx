import React from "react";
export default function AccountActionLanding({ onNavigate }) {
  return <main className="auth-page"><section className="auth-card"><h1>Return to your account action</h1>
    <p>Opening this link makes no account change. Its confirmation code has been removed from this page’s address.</p>
    <p>Return to the original AQUA tab and paste the complete link from your email into the matching confirmation field. Then verify and confirm the change there.</p>
    <p>If the original action was closed, reloaded, or started in another browser, start a new account action. This page cannot restore it.</p>
    <button type="button" onClick={() => onNavigate("/settings")}>Go to AQUA settings</button>
  </section></main>;
}
