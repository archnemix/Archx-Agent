import test from 'node:test';
import assert from 'node:assert/strict';
import { createChatWriter } from '../public/js/chat-persistence.mjs';
import { applyChatFailure } from '../public/js/chat-failure.mjs';

function writer(write, options = {}) {
  return createChatWriter(write, { schedule: () => 1, cancel: () => {}, ...options });
}
test('concurrent chats both reach the save queue, with the latest version per chat', async () => {
  const saved = [];
  const w = writer(async (chat, active) => saved.push([chat.id, chat.content, active]), { getActiveId: () => 'b' });
  w.queue({id:'a',content:'old'}); w.queue({id:'b',content:'second'}); w.queue({id:'a',content:'latest'});
  assert.deepEqual(await w.flush(), [true,true]);
  assert.deepEqual(saved, [['a','latest','b'],['b','second','b']]);
  assert.deepEqual(await w.flush(), []);
});
test('one failed save is reported and does not discard another chat', async () => {
  const errors = []; const saved = [];
  const w = writer(async chat => { if(chat.id === 'a') throw new Error('offline'); saved.push(chat.id); }, {onError:(e,id)=>errors.push([id,e.message])});
  w.queue({id:'a'}); w.queue({id:'b'});
  assert.deepEqual(await w.flush(), [false,true]);
  assert.deepEqual(saved,['b']); assert.deepEqual(errors,[['a','offline']]);
});
test('updates queued during a write are kept for the next batch', async () => {
  let w; const saved=[];
  w=writer(async c=>{saved.push(c.content);if(c.content==='first')w.queue({id:'a',content:'second'});});
  w.queue({id:'a',content:'first'}); await w.flush(); await w.flush();
  assert.deepEqual(saved,['first','second']);
});
test('invalid chat records cannot overwrite a pending chat', async () => {
  const saved=[]; const w=writer(async c=>saved.push(c.id));
  w.queue({id:'a'});w.queue(null);w.queue({});await w.flush();assert.deepEqual(saved,['a']);
});
test('provider error preserves partial answer, reasoning and routed metadata', () => {
  const m={content:'Partial answer',reasoning:'Returned thinking',pending:true,meta:{model:'original',provider:'fallback'}};
  applyChatFailure(m,new Error('Connection interrupted'),{elapsed:200});
  assert.equal(m.content,'Partial answer');assert.equal(m.reasoning,'Returned thinking');
  assert.equal(m.errorMessage,'Connection interrupted');assert.equal(m.meta.model,'original');
  assert.equal(m.meta.provider,'fallback');assert.equal(m.meta.incomplete,true);assert.equal(m.pending,false);
});
test('Stop is not treated as a provider failure', () => {
  const m={content:'Some output',meta:{model:'original'},pending:true};
  applyChatFailure(m,new Error('aborted'),{stopped:true});
  assert.equal(m.content,'Some output');assert.equal(m.meta.stopped,true);assert.equal(m.error,undefined);
});
test('empty stopped output gets an explicit stopped state',()=>{
  const m={content:'',meta:{}};applyChatFailure(m,{name:'AbortError'});assert.equal(m.content,'_stopped_');
});

test('chat lifecycle reuses matching empty drafts and locks specialised modes', async () => {
 const {findDraft,isPersistentChat,canConvertMode}=await import('../public/js/chat-lifecycle.mjs');
 const draft={id:'draft',modeId:'simple-chat',messages:[]};
 assert.equal(findDraft([draft],false),draft);assert.equal(findDraft([draft],true),undefined);
 assert.equal(isPersistentChat(draft),false);
 assert.equal(isPersistentChat({...draft,messages:[{content:'real'}]}),true);
 assert.equal(isPersistentChat({...draft,ephemeral:true,messages:[{content:'private'}]}),false);
 assert.equal(canConvertMode('simple-chat','agent',['simple-chat','agent']),true);
 assert.equal(canConvertMode('simple-chat','agent',['simple-chat']),false);
 assert.equal(canConvertMode('agent','simple-chat',['simple-chat','agent']),false);
 assert.equal(canConvertMode('agent','research',['simple-chat','agent','research']),false);
});
