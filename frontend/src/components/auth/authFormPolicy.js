// UI guidance mirrors the reviewed server policy. The server remains authoritative.
export function validateNewPassword(password, confirmation) {
  if (typeof password !== "string" || typeof confirmation !== "string") return "Enter and confirm your new password.";
  const normalized = password.normalize("NFC");
  const length = [...normalized].length;
  if (length < 15 || length > 128 || new TextEncoder().encode(normalized).length > 512) return "Use a password with 15–128 characters.";
  if (normalized !== confirmation.normalize("NFC")) return "Your passwords do not match.";
  return "";
}

export function passwordFailureMessage(error, { proof = false } = {}) {
  // Never render server bodies, user values, token strings or unknown Error messages.
  if (error?.code === "invalid_proof") return "This link is invalid, expired or already used. Request a new email to continue.";
  if (error?.status === 401) return "We couldn’t verify that email and password. Please try again.";
  if (error?.status === 403) return "This attempt expired. Submit the form again to start a fresh attempt.";
  if (error?.status === 422) return proof ? "Choose a different, unique password with 15–128 characters. Common or compromised passwords are not accepted." : "Check your email address and password, then try again.";
  if (error?.status === 429) return "Too many attempts. Please wait before trying again.";
  if (error?.code === "busy") return "Another account action is in progress. Please wait for it to finish.";
  return "This account action is temporarily unavailable. Please try again later.";
}
