import { isRecord, validId, validProgress, requireContract, submissionRecord, lifecycleRecord } from "./workspaceContract.js";

export function analysisSnapshot(value, id) {
  const snapshot = submissionRecord(value);
  requireContract(snapshot.request.id === id);
  return { ...snapshot, request: { ...snapshot.request, ...lifecycleRecord(value.request) } };
}

export function analysisEvent(type, id, encoded, requestId) {
  requireContract(["progress", "snapshot-required"].includes(type) && typeof encoded === "string");
  let value; try { value = JSON.parse(encoded); } catch { requireContract(false); }
  requireContract(isRecord(value) && Object.keys(value).sort().join(",") === "request_id,sequence,stage,state,version"
    && validId(value.request_id) && value.request_id === requestId && validProgress(value)
    && Number.isSafeInteger(value.sequence) && value.sequence >= 0 && id === `${requestId}:${value.sequence}`);
  return { requestId, sequence: value.sequence, version: value.version, state: value.state, stage: value.stage, snapshotRequired: type === "snapshot-required" };
}

// SSE lines may span chunks. Only fixed metadata events reach application state;
// an unfinished frame at EOF is discarded, as required by the event-stream format.
export function eventParser(requestId, onEvent) {
  let line = "", lineBytes = 0, frame = { data: [], event: "", id: "" }, frameSize = 0, sawCR = false;
  const emitLine = () => {
    frameSize += lineBytes;
    requireContract(frameSize <= 8192);
    if (!line) {
      if (frame.data.length) onEvent(analysisEvent(frame.event, frame.id, frame.data.join("\n"), requestId));
      frame = { data: [], event: "", id: "" }; frameSize = 0;
    } else if (!line.startsWith(":")) {
      const colon = line.indexOf(":"), key = colon < 0 ? line : line.slice(0, colon);
      let value = colon < 0 ? "" : line.slice(colon + 1); if (value.startsWith(" ")) value = value.slice(1);
      if (key === "data") frame.data.push(value);
      else if (key === "event") frame.event = value;
      else if (key === "id") { requireContract(!value.includes("\0")); frame.id = value; }
    }
    line = ""; lineBytes = 0;
  };
  return (chunk) => {
    for (const character of chunk) {
      if (character === "\n" && sawCR) { sawCR = false; continue; }
      sawCR = character === "\r";
      if (character === "\n" || sawCR) emitLine();
      else { line += character; const code = character.codePointAt(0); lineBytes += code <= 127 ? 1 : code <= 2047 ? 2 : code <= 65535 ? 3 : 4;
        requireContract(lineBytes + frameSize <= 8192); }
    }
  };
}
