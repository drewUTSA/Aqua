import { AssertionError } from "node:assert";

// Fixed report vocabulary. Intercepted requests can also fail in URL parsing,
// the fixture bridge, or a response gate. Their raw errors can contain input.
const failureCodes = new Set([
  "browser_protocol_failed", "browser_closed", "browser_pipe_closed", "browser_protocol_deadline",
  "browser_suite_deadline", "browser_protocol_invalid_frame", "browser_protocol_frame_bound",
  "browser_protocol_invalid_json", "browser_protocol_unmatched_response", "browser_protocol_pending_bound",
  "browser_protocol_method_rejected", "browser_event_failed", "browser_start_failed",
  "bridge_closed", "bridge_exited", "bridge_input_bound", "bridge_invalid_json", "bridge_invalid_response",
  "bridge_operation_failed", "bridge_output_bound", "bridge_pipe_closed", "bridge_request_timeout",
  "bridge_start_failed", "bridge_startup_failed", "bridge_startup_timeout", "bridge_stderr_bound",
  "bridge_unmatched_response", "request_bound", "request_body_bound", "response_body_bound",
]);
const fetchMethods = new Set(["Fetch.fulfillRequest", "Fetch.continueRequest", "Fetch.failRequest"]);
const protocolReasons = new Set(["request_no_longer_exists", "target_no_longer_exists", "other_protocol_error"]);

export function describeInterceptionFailure(error) {
  if (error instanceof AssertionError) return { category: "bridge_contract_assertion" };
  const message = error?.message;
  const category = failureCodes.has(message) ? message : "intercepted_request_failed";
  if (category === "browser_protocol_failed") {
    const { reason, method, protocol_reason: protocolReason } = error.browserDiagnostic ?? {};
    if (reason === category && fetchMethods.has(method) && protocolReasons.has(protocolReason)
        && protocolReason === error.protocolReason) {
      return { category, fetch: { method, protocol_reason: protocolReason } };
    }
  }
  return { category };
}
