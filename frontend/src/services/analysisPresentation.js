const stages = {
  checking: "Checking saved analysis", queued: "Queued", context: "Preparing conversation context", schema: "Checking the data structure",
  retrieval: "Finding relevant data", generating: "Preparing a query", validating: "Checking the query", executing: "Running the approved query",
  summarizing: "Preparing the answer", persisting: "Saving the answer", cancelling: "Cancellation requested", complete: "Analysis complete",
  error: "Analysis failed", cancelled: "Analysis cancelled on the server", interrupted: "Analysis interrupted", expired: "Analysis deadline reached"
};
export const analysisLabel = (request) => stages[request?.stage] || "Checking saved analysis";
export function analysisConnectionLabel(connection) {
  return ({ connecting: "Connecting to saved status.", polling: "Checking saved status periodically.", offline: "Connection interrupted. Reconnecting to saved status.",
    unavailable: "Saved status is unavailable. Reconnect to check it.", "cancel-requested": "Asking the server to cancel. Cancellation is not yet confirmed.",
    "cancel-unconfirmed": "Cancellation could not be confirmed. Check saved status before trying again." })[connection] || "";
}
