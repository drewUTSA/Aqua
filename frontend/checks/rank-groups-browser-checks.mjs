import assert from "node:assert/strict";
import { openDrafts } from "./homepage-browser-actions.mjs";

// Both production shells share a durable employee composer. This fixture checks
// its actual controls and submitted API text, independently of SQL qualification.
export async function rankGroupsJourney({ navigate, signIn, viewport, click, fill, evaluate, check, waitFor, key, fixture }) {
  await viewport(320, 740, true);
  await navigate(); await signIn();
  const box = ".opal-composer textarea", scope = ".rank-groups__form";
  const query = selector => `document.querySelector(${JSON.stringify(selector)})`;
  const change = (name, value) => evaluate(`(() => {
    const el=${query(scope + ' select[name="' + name + '"]')};
    el.value=${JSON.stringify(value)}; el.dispatchEvent(new Event('change',{bubbles:true})); return true;
  })()`);
  const input = (name, value) => fill(`${scope} input[name="${name}"]`, value);
  const original = "Which meters have the largest totals?";
  const openRank = async () => {
    await evaluate(`${query(".rank-groups summary")}.focus();true`); await key("Enter", 0, "\r");
    await waitFor(`Boolean(${query(".rank-groups[open]")})`, "rank_keyboard_open");
  };
  await waitFor(`Boolean(${query(".rank-groups summary")})`, "signed_in_rank_action");
  await fill(box, original); await openRank();
  await waitFor(`document.activeElement===${query(scope + ' input[name="source"]')}`, "typed_rank_source_focus");
  await input("source", "readings"); await input("group", "meters");
  await click(scope + ' button[type="button"]');
  await check("Back to my question keeps the original text intact and restores keyboard focus",
    `!${query(".rank-groups[open]")} && ${query(box)}.value===${JSON.stringify(original)} && document.activeElement===${query(box)}`);
  await openRank();
  await click(scope + ' button[type="submit"]');
  await check("Taking the preview opens a separate editable draft and leaves sending to the employee",
    `${query(box)}.value==='Rank groups: From readings, show the top 3 meters by row count, including ties.' && document.activeElement===${query(box)}`);
  assert.equal(fixture.queryCount(), 0, "typed_rank_preparation_must_not_send");
  await fill(box, ""); await openRank();
  await check("Rank groups is keyboard accessible and blocks an incomplete draft",
    `${query(scope + " button")}.disabled && !${query(scope + ' input[name="field"]')}`);
  await input("source", "readings"); await input("group", "meters");
  await check("Count previews cutoff ties in the editable question", `${query(".rank-groups__preview")}.textContent.endsWith('Rank groups: From readings, show the top 3 meters by row count, including ties.')`);
  await change("direction", "bottom"); await change("ties", "fixed"); await change("measure", "total");
  await check("Total requires a field", `${query(scope + " button")}.disabled && !!${query(scope + ' input[name="field"]')}`);
  await input("field", "usage"); await input("number", "2");
  await check("Fixed groups have their own explicit preview", `${query(".rank-groups__preview")}.textContent.endsWith('Rank groups: From readings, show exactly the bottom 2 meters by total usage.')`);
  await change("ties", "levels");
  const draft = "Rank groups: From readings, which meters have one of the lowest 2 distinct total usage values?";
  await check("Every field and the distinct-score preview fit a narrow mobile viewport", `
    ${query(".rank-groups__preview")}.textContent.endsWith(${JSON.stringify(draft)}) && document.documentElement.scrollWidth<=innerWidth+1 &&
    [...${query(scope)}.querySelectorAll('input,select,button')].every(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.left>=0&&r.right<=innerWidth+1&&r.height>=43.9;})`);
  await click(scope + ' button[type="submit"]');
  await check("Use this draft focuses the ordinary composer and leaves Send under employee control", `
    ${query(box)}.value===${JSON.stringify(draft)} && document.activeElement===${query(box)} && !${query(".rank-groups")}`);
  const edited = draft.replace("lowest 2", "lowest 4");
  await fill(box, edited);
  assert.equal(fixture.queryCount(), 0, "opening_previewing_applying_and_editing_must_not_send");
  await click('[aria-label="Send message"]');
  await waitFor(`Boolean(${query(".conversation .message--aqua")})`, "rank_chat_response");
  const submissions = fixture.calls.filter(call => call.path === "/api/v1/chats" && call.method === "POST");
  assert.equal(submissions.length, 1, "only_the_employee_send_creates_a_question");
  assert.equal(submissions[0].body.question, edited, "employee_edits_are_the_exact_submitted_text");
  await check("The explicit Send is saved literally and the tool is absent from history",
    `${query(".conversation .message--user")}.textContent.includes(${JSON.stringify(edited)}) && !${query(".rank-groups")} && !${query("[data-rank-ties]")}`);
  await openDrafts({ evaluate, click, waitFor });
  await click(".refined-recovery-dialog .refined-search-results button");
  await waitFor(`${query(box)}?.value===${JSON.stringify(original)}`, "original_unsent_ranking_restored");
  assert.equal(fixture.queryCount(), 1, "restoring_the_original_must_not_send");
  fixture.queryTables = [{ id: "result", title: "Meter totals", columns: [{ key: "meter", label: "Meter", type: "string" },
    { key: "total", label: "Total", type: "number" }], rows: [{ meter: "Orchard", total: 9 }] }];
  await click('[aria-label="Send message"]');
  await waitFor(`Boolean(${query("[data-rank-ties]")})`, "saved_ordinary_ranking_action");
  const beforeReview = fixture.calls.length;
  await evaluate(`${query("[data-rank-ties]")}.focus();true`); await key("Enter", 0, "\r");
  await waitFor(`Boolean(${query(".rank-groups[open]")})`, "saved_rank_keyboard_open");
  await check("Choosing tie rules from a saved table focuses Source and leaves every ranking choice to the employee", `
    document.activeElement===${query(scope + ' input[name="source"]')} && ${query(box)}.value==='' &&
    [...${query(scope)}.querySelectorAll('input,select')].every(el=>el.value==='') &&
    ${query(scope + ' button[type="submit"]')}.disabled && !${query(".rank-groups__preview")}`);
  await input("source", "readings"); await input("group", "meters"); await input("number", "2");
  await change("measure", "count"); await change("direction", "top");
  await check("Preview waits for an explicit tie rule", `${query(scope + ' button[type="submit"]')}.disabled && !${query(".rank-groups__preview")}`);
  await change("ties", "peers");
  await click(scope + ' button[type="submit"]');
  await check("A new editable question explicitly includes ties and waits for Send", `
    ${query(box)}.value==='Rank groups: From readings, show the top 2 meters by row count, including ties.' && document.activeElement===${query(box)}`);
  assert.equal(fixture.queryCount(), 2, "opening_a_saved_rank_and_preparing_its_draft_must_not_submit");
  assert.ok(fixture.calls.slice(beforeReview).every(call => call.method === "GET"), "saved_review_never_writes");
  fixture.canQuery = false;
  await navigate("/");
  await waitFor(`${query(box)}?.disabled===true`, "rank_restricted_workspace");
  await check("A signed-in employee without a grant has no ranking controls", `!${query(".rank-groups")}`);
}
