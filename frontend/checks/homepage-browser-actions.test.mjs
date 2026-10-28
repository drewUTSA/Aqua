import test from 'node:test';
import assert from 'node:assert/strict';
import {runInNewContext} from 'node:vm';
import {openDrafts} from './homepage-browser-actions.mjs';

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
