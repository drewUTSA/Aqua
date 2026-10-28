import React from "react";
import { formatTimestamp } from "../../services/preferenceFormatting.js";

export default function ResultMetadata({ response, preferences }) {
  const value = response.resultMetadata;
  if (!value) return null;
  return <div className="result-metadata">
    {response.precisionNote && <p>{response.precisionNote}</p>}
    {value.truncated && <p>Results are truncated at {value.max_rows} rows.</p>}
    {preferences?.timestamps === "always" && <p>Generated <time dateTime={value.generated_at} title={value.generated_at}>{formatTimestamp(value.generated_at, preferences)}</time></p>}
    <details><summary>Result details</summary>
      <p>Source <code title={value.source.id}>{value.source.id.slice(0, 12)}</code></p>
      {!["always", "hidden"].includes(preferences?.timestamps) && <p>Generated <time dateTime={value.generated_at} title={value.generated_at}>{preferences ? formatTimestamp(value.generated_at, preferences) : new Date(value.generated_at).toLocaleString()}</time></p>}
      <p>{value.source.freshness_at ? <>Source freshness <time dateTime={value.source.freshness_at} title={value.source.freshness_at}>{preferences ? formatTimestamp(value.source.freshness_at, preferences) : new Date(value.source.freshness_at).toLocaleString()}</time></> : "Source freshness is unavailable."}</p>
      <p>{response.presentation?.charts?.length ? "Filters and SQL aggregation are unspecified. Proven chart units are shown with the visual." : "Filters, aggregation and column units are unspecified."}</p>
    </details>
  </div>;
}
