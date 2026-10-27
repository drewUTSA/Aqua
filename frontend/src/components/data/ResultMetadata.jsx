import React from "react";

export default function ResultMetadata({ response }) {
  const value = response.resultMetadata;
  if (!value) return null;
  return <div className="result-metadata">
    {response.precisionNote && <p>{response.precisionNote}</p>}
    {value.truncated && <p>Results are truncated at {value.max_rows} rows.</p>}
    <details><summary>Result details</summary>
      <p>Source <code title={value.source.id}>{value.source.id.slice(0, 12)}</code></p>
      <p>Generated <time dateTime={value.generated_at}>{new Date(value.generated_at).toLocaleString()}</time></p>
      <p>{value.source.freshness_at ? <>Source freshness <time dateTime={value.source.freshness_at}>{new Date(value.source.freshness_at).toLocaleString()}</time></> : "Source freshness is unavailable."}</p>
      <p>Filters, aggregation and column units are unspecified.</p>
    </details>
  </div>;
}
