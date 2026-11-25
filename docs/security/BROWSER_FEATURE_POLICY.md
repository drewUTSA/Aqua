# Browser capability policy

The November 25 security review configures 50 explicit empty allowlists in
`frontend/nginx.conf`. They deny unused device, capture, credential, advertising,
browser AI, deferred network, installation and local-network APIs. `clipboard-write`
remains available for explicit Copy controls, and `identity-credentials-get`
remains available for Google Identity Services/FedCM.

The installed Chromium browser reports 81 policy features. All 50 explicitly
denied features are disabled; its existing default also disables `unload`. The
remaining 30 allowed entries are deliberately retained:

- 24 client-hint controls preserve browser and vendor compatibility, including
  preference, viewport, device and user-agent negotiation. Aqua does not add an
  `Accept-CH` request or new telemetry.
- `focus-without-user-activation` and `aria-notify` preserve focus management and
  accessible browser/vendor controls.
- `identity-credentials-get` and `storage-access` preserve the supported Google
  identity flow and its browser-dependent cookie/FedCM behavior.
- `clipboard-write` supports employee-initiated copying.
- `cross-origin-isolated` preserves the browser's isolation capability. This
  permission alone does not enable isolation; Aqua keeps its existing popup
  compatibility and does not add a cross-origin embedder policy.

The production-source browser fixture checks supported entries against the
explicit deny list, checks that Copy and identity remain allowed, and completes
registration, password sign-in, synthetic Google sign-in, table copying and
ordinary local API requests. A separate anonymous browser loads the real Google
SDK and verifies cross-origin popup communication. These checks do not complete
a real Google account consent flow.

Unsupported directives are not counted as enforcement evidence. The policy
does not claim to control future browser features automatically. Revisit this
list before adding a browser capability and when supported browser versions
change; do not disable accessibility or identity capabilities merely to reduce
the count of allowed entries.

Primary references: [Chrome Permissions Policy](https://developer.chrome.com/docs/privacy-security/permissions-policy),
[Google FedCM requirements](https://developers.google.com/identity/gsi/web/guides/fedcm-migration),
and [Google's popup and CSP setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid).
