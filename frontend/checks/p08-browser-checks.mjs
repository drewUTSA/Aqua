// Actual Plotly and application actions over fixed synthetic private results.
import { assertEssentialControls, assertShell } from "./p05-shell-browser-checks.mjs";
import { accountAction, startBlankChat } from "./homepage-browser-actions.mjs";
const q = JSON.stringify;
const plot = "document.querySelector('.visual-pane .js-plotly-plot')";
const paneText = "document.querySelector('.visual-pane')?.textContent";

export async function runVisualChecks(ctx) {
  const { check, evaluate, waitFor, click, clickText, fill } = ctx;
  await assertShell(check);
  let jobs = 0;
  async function submit(question) {
    if (jobs && jobs % 3 === 0) await ctx.bridge.send("workspace_recover_analysis_rate");
    const before = await evaluate("document.querySelectorAll('.conversation .message--user').length");
    await fill(".opal-composer textarea", question); await click('[aria-label="Send message"]'); jobs++;
    await waitFor(`document.querySelectorAll('.conversation .message--user').length>${before}&&Boolean(document.querySelector('.analysis-status[data-analysis-state=complete],.analysis-status[data-analysis-state=error]'))&&!document.querySelector('[aria-label="Cancel analysis"]')`, "synthetic_analysis_terminal");
  }
  async function ready() { await waitFor("Boolean(document.querySelector('.visual-pane:not([hidden]) .plotly-chart[data-chart-status=ready] .js-plotly-plot'))", "actual_plotly_ready"); }
  async function newChat() { await startBlankChat(ctx); await waitFor("!document.querySelector('.visual-pane')", "new_chat_removes_previous_visual"); }
  async function retainNode() { await evaluate(`window.__p08Previous=${plot};true`); }
  async function purged(label) { const condition = "Boolean(window.__p08Previous)&&!window.__p08Previous.data&&!window.__p08Previous._fullData"; await waitFor(condition, "owned_plot_purged"); await check(label, condition); await evaluate("delete window.__p08Previous;true"); }
  async function setSize(width, height = 900) { await ctx.cdp.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false }); await waitFor(`innerWidth===${width}`, "viewport_set"); }
  async function dragZoom() {
    // Exercise the actual installed engine handlers, without changing layout.
    await evaluate(`(()=>{const el=${plot}.querySelector('.nsewdrag'),r=el.getBoundingClientRect(),x=r.left+r.width*.2,y=r.top+r.height*.2;el.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,clientX:x,clientY:y,buttons:1,button:0}));document.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,clientX:r.left+r.width*.7,clientY:r.top+r.height*.7,buttons:1}));document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true,clientX:r.left+r.width*.7,clientY:r.top+r.height*.7,button:0}));return true})()`);
    await waitFor(`${plot}.layout.xaxis.autorange===false&&JSON.stringify(${plot}._fullLayout.xaxis.range)!==window.__p08FullRange`, "actual_drag_zoom_applied");
  }

  await check("new authenticated chat has no visual split or loaded Plotly engine", "!document.querySelector('.visual-pane,.visual-divider')&&!performance.getEntriesByType('resource').some(x=>/PlotlyChart|plotly-basic/i.test(x.name))");
  await submit("P08 text explanation");
  await check("ordinary text response keeps a single conversation and defers Plotly", "!document.querySelector('.visual-pane,.visual-divider')&&!performance.getEntriesByType('resource').some(x=>/PlotlyChart|plotly-basic/i.test(x.name))");
  await newChat(); await submit("P08 chart primitives"); await ready();
  await check("actual Plotly preserves zero negative and missing gap values", `(()=>{const p=${plot};return p.data.length===1&&JSON.stringify(p.data[0].y)==='[0,-12.5,null]'&&p.data[0].connectgaps!==true})()`);
  ctx.engineConfiguration = await evaluate(`(()=>{const c=${plot}._context;return Object.fromEntries(['displayModeBar','showLink','showSendToCloud','sendData','typesetMath'].map(k=>[k,c[k]===undefined?'unsupported':c[k]===false?'disabled':c[k]===true?'enabled':'other']))})()`);
  await check("actual engine disables cloud links math and modebar", `(()=>{const c=${plot}._context;return c.displayModeBar===false&&c.showLink!==true&&c.showSendToCloud===false&&c.sendData!==true&&c.typesetMath===false&&![...document.querySelectorAll('.visual-pane .modebar')].some(e=>e.getClientRects().length)})()`);
  await clickText("Pan", ".plotly-chart__controls button"); await waitFor(`${plot}.layout.dragmode==='pan'`, "actual_pan_control");
  await clickText("Zoom", ".plotly-chart__controls button"); await waitFor(`${plot}.layout.dragmode==='zoom'`, "actual_zoom_control");
  ctx.stage = "active_chart_control_contrast";
  ctx.activeControlContrast = await evaluate("(()=>{const s=getComputedStyle(document.querySelector('.plotly-chart__controls button[aria-pressed=true]'));const luminance=rgb=>{const c=rgb.match(/[\\d.]+/g).slice(0,3).map(n=>Number(n)/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4);return c[0]*.2126+c[1]*.7152+c[2]*.0722;};const a=luminance(s.color),b=luminance(s.backgroundColor);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05)})()");
  if (!Number.isFinite(ctx.activeControlContrast) || ctx.activeControlContrast < 4.5) throw Error("active_control_contrast_insufficient");
  ctx.results.push({ check: "active Zoom control computed text contrast is at least 4.5:1", passed: true });
  await evaluate("document.querySelector('.visual-divider').focus();true");
  const dividerBefore = await evaluate("Number(document.querySelector('.visual-divider').getAttribute('aria-valuenow'))");
  await ctx.cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "ArrowRight", code: "ArrowRight" });
  await check("keyboard separator changes the bounded conversation width", `(()=>{const e=document.querySelector('.visual-divider'),n=Number(e.getAttribute('aria-valuenow'));return n>${dividerBefore}&&n<=Number(e.getAttribute('aria-valuemax'))})()`);
  await ctx.screenshot("desktop-actual-plotly");

  await evaluate(`window.__p08FullRange=JSON.stringify(${plot}._fullLayout.xaxis.range);true`); await dragZoom();
  await evaluate(`window.__p08Zoom=JSON.stringify(${plot}.layout.xaxis.range);true`);
  await clickText("Table", '.visual-pane [aria-label="Result view"] button');
  await check("table tab keeps the same chart instance and zoom", `Boolean(${plot})&&JSON.stringify(${plot}.layout.xaxis.range)===window.__p08Zoom&&Boolean(${plot}.closest('[hidden]'))`);
  await clickText("Chart", '.visual-pane [aria-label="Result view"] button'); await ready();
  await setSize(390, 844); await waitFor("Boolean(document.querySelector('.visual-workspace--mobile'))", "mobile_visual_layout");
  await clickText("Visuals", '.visual-workspace__tabs button'); await ready();
  await evaluate("document.querySelector('.visual-pane__scroll').scrollTop=40;document.querySelector('.visual-pane__scroll').dispatchEvent(new Event('scroll'));true");
  const position = await evaluate("document.querySelector('.visual-pane__scroll').scrollTop");
  if (position <= 0) throw Error("mobile_scroll_fixture_not_exercised");
  await clickText("Conversation", '.visual-workspace__tabs button');
  await check("mobile conversation tab hides and retains the chart", `Boolean(${plot})&&Boolean(${plot}.closest('[hidden]'))&&JSON.stringify(${plot}.layout.xaxis.range)===window.__p08Zoom`);
  await clickText("Visuals", '.visual-workspace__tabs button'); await ready();
  await check("mobile tab return preserves zoom and scroll", `JSON.stringify(${plot}.layout.xaxis.range)===window.__p08Zoom&&document.querySelector('.visual-pane__scroll').scrollTop===${position}`);
  for (const width of [320, 740]) { await setSize(width, 844); await assertEssentialControls(check, `composer remains reachable at ${width}px with visual active`); }
  await setSize(1440); await waitFor("Boolean(document.querySelector('.visual-divider'))", "desktop_split_restored");
  await clickText("Reset chart", ".plotly-chart__controls button"); await waitFor(`${plot}.layout.xaxis.autorange===true`, "actual_chart_reset");
  await dragZoom();
  await submit("Now by category"); await ready();
  await waitFor(`${paneText}.includes('Chart context changed')&&${plot}.data[0].y[1]===-25&&JSON.stringify(${plot}._fullLayout.xaxis.range)===window.__p08FullRange`, "filtered_result_draw_completed");
  await check("changed filtered query resets chart context and declares the change", `${paneText}.includes('Chart context changed')&&JSON.stringify(${plot}._fullLayout.xaxis.range)===window.__p08FullRange&&${plot}.data[0].y[1]===-25`);
  await retainNode(); await clickText("Close visuals", ".visual-pane button");
  await waitFor("!document.querySelector('.visual-pane')", "visual_close_completed");
  await purged("closing visuals purges the actual engine data");
  await waitFor("document.activeElement.matches('.visual-result-open,.opal-composer textarea')", "close_focus_restored");
  await check("closing visuals returns focus to its result or composer", "document.activeElement.matches('.visual-result-open,.opal-composer textarea')");
  await submit("Now by category");
  await check("completed visual follow-up cannot reopen a dismissed pane", "!document.querySelector('.visual-pane')");
  await evaluate("[...document.querySelectorAll('.visual-result-open')].at(-1).click();true");
  await ready(); await check("saved follow-up renders its own latest values", `${plot}.data[0].y[1]===-25`);
  await submit("P08 chart failure");
  await waitFor(`${plot}.data[0].y[1]===-25&&${paneText}.includes('Showing the previous result.')`, "failed_visual_update_rendered");
  await check("failed visual update keeps previous chart with truthful failure", `${plot}.data[0].y[1]===-25&&${paneText}.includes('Showing the previous result.')`);
  await clickText("Retry visual update", ".visual-pane button"); jobs++;
  await waitFor(`${paneText}.includes('Showing the previous result.')&&!document.querySelector('.visual-pane button:disabled')`, "visual_retry_terminal");
  await check("explicit failed retry retains the previous owned visual", `${plot}.data[0].y[1]===-25`);
  await ctx.screenshot("sticky-failed-update");

  await retainNode(); await newChat(); await purged("switching chats purges the prior result instance");
  await submit("P08 chart hostile labels"); await ready();
  await check("actual SVG renders hostile labels as literal text without elements", `(()=>{const p=${plot};return p.textContent.includes('<img')&&!p.querySelector('img,a,image,foreignObject')&&typeof window.PRIVATE==='undefined'})()`);
  await clickText("Table", '.visual-pane [aria-label="Result view"] button');
  await evaluate("(()=>{window.__p08Export='';Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{window.__p08Export=value;}}});return true})()");
  await clickText("Copy table", ".visual-pane button");
  await check("actual copy action escapes formula-looking labels and preserves negative values", "window.__p08Export.includes(\"'  =HYPERLINK\")&&window.__p08Export.includes('-1')");
  await evaluate("(()=>{const blobs=new Map(),create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL),click=HTMLAnchorElement.prototype.click;window.__p08Csv='';URL.createObjectURL=blob=>{if(blobs.size>=2)throw Error();const url=create(blob);blobs.set(url,blob);return url;};URL.revokeObjectURL=url=>{blobs.delete(url);revoke(url);};HTMLAnchorElement.prototype.click=function(){const blob=blobs.get(this.href);if(this.download==='result.csv'&&blob){void(async()=>{const b=new Uint8Array(await blob.arrayBuffer());window.__p08CsvBom=b[0]===239&&b[1]===187&&b[2]===191;window.__p08Csv=await blob.text();})();return;}return click.call(this);};return true})()");
  await clickText("Download CSV", ".visual-pane button"); await waitFor("window.__p08Csv.length>0", "actual_csv_blob_generated");
  await check("actual CSV action preserves quoted literal labels and true negative numbers", "window.__p08CsvBom===true&&window.__p08Csv.includes(\"' \\t=HYPERLINK\")&&window.__p08Csv.includes('\"-1\"')");
  await newChat(); await submit("P08 chart UTC time"); await ready();
  await check("Python aware timestamps reach UTC chart coordinates without changing table", `${plot}.data[0].x[0]==='2026-01-01T00:00:00.000Z'&&${plot}.data[0].x[1]==='2026-01-01T01:00:00.000Z'&&${paneText}.includes('Time axis: UTC')`);
  await clickText("Table", '.visual-pane [aria-label="Result view"] button');
  await check("temporal table keeps full original offsets and does not invent unknown currency", `${paneText}.includes('2026-01-01T00:00:00+00:00')&&${paneText}.includes('2025-12-31T20:00:00-05:00')&&!${paneText}.includes('$')`);
  await evaluate("window.__p08Export='';true"); await clickText("Copy table", ".visual-pane button");
  await check("temporal copy keeps original date time and offsets", "window.__p08Export.includes('2026-01-01T00:00:00+00:00')&&window.__p08Export.includes('2025-12-31T20:00:00-05:00')&&!window.__p08Export.includes('$')");
  await newChat(); await submit("P08 chart exact values");
  await check("exact values use a table without approximate chart coordinates", `!${plot}&&${paneText}.includes('9007199254740993')&&${paneText}.includes('-0.1234567890123456789')&&${paneText}.includes('Chart approximation is disabled')`);
  await newChat(); await submit("P08 chart oversized");
  await check("51 bars remain table-only with no silent sampling", `!${plot}&&${paneText}.includes('chart point limit')`);
  await ctx.screenshot("honest-point-limit-fallback");

  await setSize(390, 844); await newChat(); await submit("P08 chart primitives");
  await check("mobile explicit result keeps Conversation selected and delays chart mount", "document.querySelector('.visual-workspace__tabs button[aria-pressed=true]')?.textContent==='Conversation'&&!document.querySelector('.visual-pane .js-plotly-plot')");
  await clickText("Visuals", '.visual-workspace__tabs button'); await ready();
  await evaluate("(()=>{const s=document.querySelector('.visual-pane__scroll'),c=document.querySelector('.visual-pane .plotly-chart__controls');s.scrollTop+=c.getBoundingClientRect().top-s.getBoundingClientRect().top-8;s.dispatchEvent(new Event('scroll'));return true})()");
  await check("mobile chart controls are reachable within the visual scroll region", "(()=>{const s=document.querySelector('.visual-pane__scroll').getBoundingClientRect();return [...document.querySelectorAll('.visual-pane .plotly-chart__controls button')].every(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=s.top&&r.bottom<=s.bottom;})})()");
  await ctx.screenshot("mobile-actual-plotly");
  await clickText("Close visuals", ".visual-pane button"); await waitFor("!document.querySelector('.visual-pane')", "mobile_visual_closed");
  await submit("Can you explain the chart?");
  await check("polite chart explanation keeps a dismissed pane closed", "!document.querySelector('.visual-pane,.visual-divider')");
  await click(".conversation .visual-result-open"); await clickText("Visuals", '.visual-workspace__tabs button'); await ready(); await retainNode();
  await ctx.bridge.send("workspace_revoke");
  await evaluate("(()=>{const c=new BroadcastChannel('aqua-session-events');c.postMessage({type:'changed'});c.close();return true})()");
  await waitFor("document.querySelector('.opal-composer textarea')?.disabled===true&&!document.querySelector('.visual-pane,.js-plotly-plot,.financial-table')", "grant_revocation_visible");
  await check("current grant loss removes visual data and export controls", "!document.querySelector('.visual-pane,.js-plotly-plot,.financial-table')");
  await purged("current grant loss purges the actual chart instance without navigation");
  await accountAction(ctx, 'Sign out');
  await waitFor("Boolean(document.querySelector('.auth-page'))&&!document.querySelector('.opal-workspace')", "logout_confirmed_auth_page");
  if ((await ctx.rawRequest("GET", "/api/auth/me")).status !== 401) throw Error("logout_session_not_revoked");
  await check("logout leaves no chart result or export in the authenticated shell", "!document.querySelector('.opal-workspace,.js-plotly-plot,.visual-pane')");
  return { fake_jobs_requested: jobs };
}
