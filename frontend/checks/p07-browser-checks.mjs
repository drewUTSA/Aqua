import assert from "node:assert/strict";

export async function analysisJourneys({ check, click, clickText, fill, waitFor, evaluate, navigate, screenshot, fixture, viewport }) {
  const latest = () => [...fixture.analysisRequests.keys()].at(-1);
  const waitFixture = async (condition, label) => { const until = Date.now() + 5500;
    while (!condition() && Date.now() < until) await new Promise((resolve) => setTimeout(resolve, 20)); assert.ok(condition(), label); };
  const state = (value) => `document.querySelector('.analysis-status')?.dataset.analysisState===${JSON.stringify(value)}`;
  const stage = (value) => `document.querySelector('.analysis-status')?.dataset.analysisStage===${JSON.stringify(value)}`;
  const revalidate = () => evaluate("(()=>{const channel=new BroadcastChannel('aqua-session-events');channel.postMessage({type:'changed'});channel.close();return true})()");
  const begin = async (question) => { await clickText("New chat"); await fill(".opal-composer textarea", question); await click("[aria-label='Send message']"); await waitFor(state("queued"), "p07_saved_queued"); return latest(); };
  const count = fixture.queryCount();
  const id = await begin("P07 live progress and cancellation");
  await waitFixture(() => fixture.analysisRequests.get(id).streams.size === 1, "p07_stream_open_before_progress");
  // A stage is written over an open HTTP stream, before the response ends.
  fixture.analysisChange(id, "running", "generating"); await waitFor(stage("generating"), "p07_progress_chunk_before_close");
  assert.equal(fixture.analysisRequests.get(id).streams.size, 1); assert.ok(fixture.analysisStreamFrames >= 2);
  await check("live metadata advances the UI before stream closure without showing SQL or a fabricated percentage", "document.querySelector('.analysis-status').textContent.includes('Preparing a query')&&!document.querySelector('.conversation .sql-block')&&!document.querySelector('.analysis-status').textContent.includes('%')");
  await viewport(320, 600, true);
  await check("320 pixel active analysis keeps progress and cancellation controls reachable without horizontal overflow", "(()=>{const button=document.querySelector('[aria-label=\"Cancel analysis\"]'),r=button?.getBoundingClientRect();return document.documentElement.scrollWidth<=innerWidth+1&&r&&r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1&&document.querySelector('.analysis-status').getBoundingClientRect().right<=innerWidth+1})()");
  await screenshot("p07-active-analysis-mobile-320"); await viewport(1440, 900);
  await fill(".opal-composer textarea", "Keep draft through server cancellation"); await click("[aria-label='Cancel analysis']");
  await waitFor(state("cancelling"), "p07_cancel_requested");
  await check("cancel acknowledgement stays requested until authoritative server termination", "document.querySelector('[aria-label=\"Cancellation requested\"]').disabled&&!document.querySelector('.analysis-status').textContent.includes('cancelled on the server')");
  fixture.analysisChange(id, "cancelled"); await waitFor(state("cancelled"), "p07_server_cancelled");
  await check("confirmed cancellation retains the newer draft and creates no result", "document.querySelector('.opal-composer textarea').value==='Keep draft through server cancellation'&&!document.querySelector('.conversation .sql-block')&&document.querySelector('.analysis-status').textContent.includes('cancelled on the server')");
  assert.equal(fixture.count(`/api/v1/analysis-requests/${id}/cancel`), 1);
  await screenshot("p07-server-confirmed-cancel");

  const reconnect = await begin("P07 reconnect to saved analysis"), replayCount = fixture.queryCount();
  fixture.analysisChange(reconnect, "running", "executing"); await waitFor(stage("executing"), "p07_execution_stage");
  await navigate("/"); await waitFor("document.querySelector('.desktop-sidebar')?.textContent.includes('P07 reconnect to saved analysis')", "p07_reload_recents");
  await clickText("P07 reconnect to saved analysis"); await waitFor(stage("executing"), "p07_reload_reconciles_saved_request");
  assert.equal(fixture.queryCount(), replayCount, "reconnect_must_not_resubmit");
  fixture.analysisChange(reconnect, "complete"); await waitFor(state("complete"), "p07_reconnected_terminal_snapshot");
  await check("reload reconnects by saved request ID with GET and restores one canonical result", "document.querySelectorAll('.conversation .message--user').length===1&&document.querySelectorAll('.conversation .message--aqua').length===1&&Boolean(document.querySelector('.conversation .sql-block'))");
  await screenshot("p07-reconnected-completed-history");

  fixture.analysisPollingOnly = true;
  const polling = await begin("P07 polling fallback cancellation"); fixture.analysisChange(polling, "running", "executing");
  await waitFor(stage("executing"), "p07_polling_saved_progress");
  fixture.analysisCancelFailure = true; await click("[aria-label='Cancel analysis']");
  await waitFor("document.querySelector('.analysis-status')?.textContent.includes('Cancellation could not be confirmed')", "p07_cancel_unconfirmed");
  await check("lost cancellation response never claims server cancellation", `${state("running")}&&!document.querySelector('.analysis-status').textContent.includes('cancelled on the server')`);
  fixture.analysisCancelFailure = false; await click("[aria-label='Cancel analysis']"); await waitFor(state("cancelling"), "p07_polling_cancel_requested");
  fixture.analysisChange(polling, "cancelled"); await waitFor(state("cancelled"), "p07_polling_cancelled");
  await check("event failure falls back to bounded saved-status polling and confirms terminal cancellation", "document.querySelector('.analysis-status').textContent.includes('cancelled on the server')&&!document.querySelector('.conversation .sql-block')");

  fixture.analysisPollingOnly = false;
  const late = await begin("P07 grant loss held saved result"); fixture.holdAnalysisStatus = true;
  fixture.analysisChange(late, "complete");
  await waitFixture(() => fixture.held.some((item) => item.kind === "analysis-status"), "held_authorized_snapshot_required");
  fixture.canQuery = false; await revalidate(); await waitFor("document.querySelector('.opal-composer textarea').disabled", "p07_grant_revoked");
  fixture.holdAnalysisStatus = false; await fixture.release("analysis-status");
  await check("a late authorized status snapshot cannot restore SQL after confirmed grant loss", "!document.querySelector('.conversation .sql-block')&&!document.querySelector('.conversation')?.textContent.includes('P07 synthetic completed answer')");
  fixture.canQuery = true; await revalidate(); await waitFor("!document.querySelector('.opal-composer textarea').disabled", "p07_grant_restored");
  const precision = await begin("P07 synthetic exact precision"); fixture.analysisChange(precision, "complete");
  await waitFor(state("complete"), "p07_exact_result_snapshot");
  await check("workspace precision metadata renders exact values and truncation while withholding rounded visuals", "(()=>{const text=document.querySelector('.financial-table')?.textContent;return text?.includes('9007199254740993')&&text.includes('-0.1234567890123456789')&&document.querySelector('.result-metadata')?.textContent.includes('truncated at 1000 rows')&&!document.querySelector('.dashboard-preview,.kpi-grid')})()");
  await click("[aria-label='Sort by Amount']");
  await check("table sort orders exact numeric strings numerically and preserves their original digits", "document.querySelector('.financial-table tbody tr:first-child td').textContent==='-0.1234567890123456789'&&document.querySelector('.financial-table tbody tr:last-child td').textContent==='9007199254740993'");
  await evaluate("(()=>{window.__p07CreateURL=URL.createObjectURL;window.__p07AnchorClick=HTMLAnchorElement.prototype.click;URL.createObjectURL=blob=>{window.__p07ExportBlob=blob;return window.__p07CreateURL(blob)};HTMLAnchorElement.prototype.click=function(){window.__p07ExportClick=true};return true})()");
  await clickText("Download CSV");
  await check("actual table CSV action exports exact positive and negative values without rounding or a formula bypass", "(async()=>{const text=await window.__p07ExportBlob.text();return window.__p07ExportClick&&text.includes('\"9007199254740993\"')&&text.includes('\"-0.1234567890123456789\"')&&!text.includes(\"'-0.123\")})()");
  await evaluate("(()=>{URL.createObjectURL=window.__p07CreateURL;HTMLAnchorElement.prototype.click=window.__p07AnchorClick;delete window.__p07CreateURL;delete window.__p07AnchorClick;delete window.__p07ExportBlob;delete window.__p07ExportClick;return true})()");
  await screenshot("p07-exact-table-and-result-details");
  await clickText("New chat"); await fill(".opal-composer textarea", "");
  assert.equal(fixture.queryCount(), count + 5, "lifecycle_observation_never_submits_analysis"); fixture.closeAnalysisStreams();
}
