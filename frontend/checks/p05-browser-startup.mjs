// Only the initial browser handshake runs here. The caller attaches to a page
// after this returns, so recovery can never replay an employee journey.
export async function startupHandshake({ launch, removeProfile, untouched, attempts }) {
  for (let attempt = 1; attempt <= 2; attempt++) {
    const pipe = await launch();
    let version;
    try {
      version = await pipe.ready();
    } catch (error) {
      const startup = pipe.startupObservation();
      const diagnostic = pipe.diagnostic;
      const receipt = { attempt, outcome: "failed", startup, diagnostic, cleanup: null };
      attempts.push(receipt);
      const silentTimeout = pipe.sequence === 1 && diagnostic?.reason === "browser_protocol_deadline"
        && diagnostic.stage === "browser_startup" && diagnostic.method === "Browser.getVersion"
        && diagnostic.timeout_ms === pipe.startupMs && startup.spawn_outcome === "spawned"
        && startup.write_started_ms !== null && startup.first_pipe_bytes_ms === null;
      if (attempt === 2 || !silentTimeout || !untouched()) throw error;

      await pipe.stop();
      receipt.cleanup = { child_stopped: pipe.stopped, stdio_closed: pipe.drained, profile_removed: false };
      if (!pipe.stopped || !pipe.drained) throw error;
      try { await removeProfile(); } catch { throw Error("browser_startup_profile_cleanup_failed"); }
      receipt.cleanup.profile_removed = true;
      if (!untouched() || pipe.deadline - performance.now() < pipe.startupMs) throw error;
      continue;
    }
    attempts.push({ attempt, outcome: "ready", startup: pipe.startupObservation() });
    return version;
  }
}
