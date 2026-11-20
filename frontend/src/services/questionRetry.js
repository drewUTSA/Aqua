export function questionRetryMessage(seconds, fallback) {
  // The application sends a shorter interval only for the employee's own
  // analysis window. Other quota and queue responses keep the existing copy.
  if (!/^(?:[1-9]|[1-5][0-9])$/.test(String(seconds))) return fallback;
  return `Try submitting your question again in ${seconds} ${Number(seconds) === 1 ? "second" : "seconds"}.`;
}
