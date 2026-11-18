import test from 'node:test';
import assert from 'node:assert/strict';
import {runInNewContext} from 'node:vm';
import {ensureNavigation,openDrafts} from './homepage-browser-actions.mjs';

function context(label){
  const trace=[];
  const item={textContent:label,disabled:false,getClientRects:()=>[{}],closest:()=>null,click:()=>trace.push('draft-selected')};
  return {trace,ctx:{click:async selector=>trace.push(selector),waitFor:async()=>{},evaluate:async expression=>expression.startsWith('Boolean(')?true:runInNewContext(expression,{document:{querySelectorAll:()=>[item]}})}};
}
test('the emitted browser expression selects a counted draft entry including literal parentheses',async()=>{
  const {ctx,trace}=context('Unsent drafts (12)');await openDrafts(ctx);
  assert.deepEqual(trace,['[aria-label="Recents actions"]','draft-selected']);
});
test('the emitted browser expression refuses a different or malformed menu label',async()=>{
  const {ctx,trace}=context('Unsent drafts 12');await assert.rejects(openDrafts(ctx),/draft_entry_missing/);
  assert.deepEqual(trace,['[aria-label="Recents actions"]']);
});

for (const layout of ['desktop', 'drawer']) {
  test(`navigation waits for the ${layout} controls after a session reload`, async () => {
    const menu = '.opal-account [aria-label="Account menu"]', opener = '[aria-label="Open navigation"]';
    let mounted = false, opened = false;
    const trace = [];
    const element = (shown, inert) => ({
      getClientRects: () => shown ? [{}] : [],
      closest: () => inert ? {} : null,
    });
    const document = { querySelectorAll: selectors => selectors.split(',').flatMap(selector => {
      if (selector === menu) return [element(mounted && (layout === 'desktop' || opened), !mounted)];
      if (selector === opener) return [element(mounted && layout === 'drawer', false)];
      throw Error('unexpected selector');
    }) };
    const evaluate = expression => runInNewContext(expression, { document });
    await ensureNavigation({ evaluate, waitFor(expression, label) {
      trace.push(label);
      if (!mounted) {
        assert.equal(evaluate(expression), false);
        mounted = true;
      }
      assert.equal(evaluate(expression), true);
    }, click(selector) {
      assert.equal(selector, opener);
      assert.ok(mounted && layout === 'drawer');
      trace.push('open drawer'); opened = true;
    } });
    assert.deepEqual(trace, layout === 'desktop' ? ['workspace_navigation_ready']
      : ['workspace_navigation_ready', 'open drawer', 'single_navigation_entry_ready']);
  });
}
