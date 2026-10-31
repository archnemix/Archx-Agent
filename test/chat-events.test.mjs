import test from 'node:test';
import assert from 'node:assert/strict';
import { readChatStream } from '../public/js/chat-events.mjs';
const event = value => `data: ${JSON.stringify(value)}\n\n`;
function body(text, size = 7) {
  const bytes=new TextEncoder().encode(text);
  return new ReadableStream({start(c){for(let i=0;i<bytes.length;i+=size)c.enqueue(bytes.slice(i,i+size));c.close();}});
}
for (const size of [1,2,7,1024]) test(`SSE preserves separate answer/reasoning across ${size}-byte chunks`,async()=>{
  const answers=[],reasons=[];
  const source=event({choices:[{delta:{reasoning_content:'سوچ 🤔'}}]})+event({choices:[{delta:{content:'Answer ✓'}}]})+'data: [DONE]\n\n';
  assert.equal(await readChatStream(body(source,size),{onDelta:x=>answers.push(x),onReasoning:x=>reasons.push(x)}),'Answer ✓');
  assert.deepEqual(answers,['Answer ✓']);assert.deepEqual(reasons,['سوچ 🤔']);
});
for (const key of ['reasoning','reasoning_content','thinking']) test(`supports ${key}`,async()=>{
  const reasons=[];await readChatStream(body(event({choices:[{delta:{[key]:'returned'}}]})+'data: [DONE]'),{onReasoning:x=>reasons.push(x)});
  assert.deepEqual(reasons,['returned']);
});
test('CRLF, comments and a final marker without trailing newline are supported',async()=>{
  assert.equal(await readChatStream(body(': comment\r\n\r\ndata: {"choices":[{"delta":{"content":"ok"}}]}\r\n\r\ndata: [DONE]',1)),'ok');
});
test('missing final marker fails after delivering partial text, without retry',async()=>{
  const chunks=[];await assert.rejects(readChatStream(body(event({choices:[{delta:{content:'partial'}}]})),{onDelta:x=>chunks.push(x)}),{code:'stream_incomplete'});
  assert.deepEqual(chunks,['partial']);
});
test('provider error is not mistaken for a finished answer',async()=>{
  await assert.rejects(readChatStream(body(event({error:{message:'quota'}})+'data: [DONE]\n\n')),/quota/);
});
test('malformed data is visible, not silently dropped',async()=>{
  await assert.rejects(readChatStream(body('data: {bad}\n\ndata: [DONE]\n\n')),/malformed/);
});
test('tool and fallback events reach their distinct callbacks',async()=>{
  const tools=[],meta=[];
  await readChatStream(body(event({tool:{kind:'web-search'}})+event({object:'archx.fallback',nextModel:'other'})+'data: [DONE]\n\n'),{onTool:t=>tools.push(t),onMeta:m=>meta.push(m)});
  assert.equal(tools[0].kind,'web-search');assert.equal(meta[0].nextModel,'other');
});
