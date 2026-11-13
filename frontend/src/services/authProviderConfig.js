import { fetchAuthConfig } from "./authClient.js";
export const googleUnavailable = "Google sign-in is temporarily unavailable. You can still use your AQUA password.";

export async function googleConfig(signal) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  let expired = false;
  const timer = setTimeout(() => { expired = true; controller.abort(); }, 15000);
  try { return { config: await fetchAuthConfig({ signal: controller.signal }), googleError: "" }; }
  catch (error) {
    if (!expired && error?.name === "AbortError") throw error;
    // Provider availability cannot turn off the independent password method.
    return { config: null, googleError: googleUnavailable };
  }
  finally { clearTimeout(timer); signal.removeEventListener("abort", abort); }
}
