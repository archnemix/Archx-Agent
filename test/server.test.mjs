import {test,before,after} from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {mkdtempSync,rmSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const root=mkdtempSync(path.join(os.tmpdir(),'archx-node-test-'));
process.env.XDG_CONFIG_HOME=path.join(root,'config');
const {Store}=require('../lib/store.js');
const {createApp}=require('../lib/server.js');
let store,server,upstream,url,providerId;const requests=[];
const listen=s=>new Promise(resolve=>s.listen(0,'127.0.0.1',()=>resolve(`http://127.0.0.1:${s.address().port}`)));
const call=async(route,body,method='POST')=>{
 const res=await fetch(url+route,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
 return {res,body:await res.json()};
};
before(async()=>{
 upstream=http.createServer(async(req,res)=>{
  if(req.method==='GET'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({data:[{id:'fixture-model'}]}));}
  let raw='';for await(const chunk of req)raw+=chunk;const b=JSON.parse(raw);requests.push(b);
  if(!b.stream){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({model:b.model,choices:[{message:{content:'Fixture answer',reasoning_content:'Fixture thinking'}}]}));}
  res.setHeader('Content-Type','text/event-stream');
  for(const delta of [{reasoning_content:'Fixture thinking'},{content:'Fixture answer'}])res.write(`data: ${JSON.stringify({choices:[{delta}]})}\n\n`);
  if(b.messages.at(-1).content!=='incomplete')res.write('data: [DONE]\n\n');
  res.end();
 });
 const base=await listen(upstream);store=new Store(path.join(root,'data'));server=http.createServer(createApp({store}));url=await listen(server);
 const added=await call('/api/providers',{name:'Local test fixture',baseUrl:base+'/v1'});assert.equal(added.res.status,200);providerId=added.body.provider.id;
 await call('/api/providers/'+providerId,{models:{custom:['fixture-model'],catalog:['fixture-model'],catalogInitialized:true}},'PATCH');
});
after(async()=>{
 await Promise.all([server,upstream].map(s=>new Promise(resolve=>{s.close(resolve);s.closeAllConnections();})));
 store.close();rmSync(root,{recursive:true,force:true});
});
test('health and shipped page report the reset product',async()=>{
 assert.equal((await call('/api/health',undefined,'GET')).body.version,'1.0.0');
 const page=await(await fetch(url)).text();assert.match(page,/id="model-btn"/);assert.match(page,/id="btn-stop"/);
 for(const p of ['/js/chat-events.mjs','/js/chat-persistence.mjs','/css/chat.css'])assert.equal((await fetch(url+p)).status,200);
});
test('local provider selection requires no key',async()=>{
 const selected=await call('/api/active',{providerId,model:'fixture-model'});assert.equal(selected.res.status,200);
 assert.equal(selected.body.active.model,'fixture-model');
});
test('streaming keeps reasoning and answer separate through the real application socket',async()=>{
 const start=requests.length;
 const response=await fetch(url+'/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({providerId,model:'fixture-model',stream:true,messages:[{role:'user',content:'hello'}]})});
 const text=await response.text();assert.match(text,/reasoning_content/);assert.match(text,/Fixture answer/);assert.match(text,/\[DONE\]/);
 assert.equal(requests.length-start,1);assert.equal(requests.at(-1).model,'fixture-model');
});
test('non-streaming uses the same selected provider and preserves reasoning',async()=>{
 const r=await call('/api/chat',{providerId,model:'fixture-model',stream:false,messages:[{role:'user',content:'hello'}]});
 assert.equal(r.res.status,200);assert.equal(r.body.choices[0].message.reasoning_content,'Fixture thinking');
});
test('upstream EOF without completion is an error, not a fabricated successful finish',async()=>{
 const start=requests.length;
 const response=await fetch(url+'/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({providerId,model:'fixture-model',stream:true,messages:[{role:'user',content:'incomplete'}]})});
 const text=await response.text();assert.match(text,/Fixture answer/);assert.match(text,/"error"/);assert.match(text,/unconfirmed/);assert.equal(requests.length-start,1);
});
test('both chats, reasoning and branches survive reopening the SQLite store',async()=>{
 for(const id of ['chat-a','chat-b']){
  const c={id,title:id,modeId:'simple-chat',messages:[{role:'assistant',content:'answer',reasoning:'thinking',errorMessage:'interrupted',tools:[{kind:'web-search',query:'fixture'}],ts:Date.now()}],branches:[{id:'branch-'+id,messages:[{role:'assistant',content:'older'}]}]};
  assert.equal((await call('/api/state/chat',{chat:c,activeId:'chat-b'})).res.status,200);
 }
 store.flushWrites();const reopened=new Store(path.join(root,'data'));
 try{assert.equal(reopened.state.chats.chats.length,2);assert.equal(reopened.state.chats.chats[0].messages[0].reasoning,'thinking');assert.equal(reopened.state.chats.chats[0].branches.length,1);assert.equal(reopened.state.chats.chats[0].messages[0].tools[0].query,'fixture');assert.equal(reopened.state.chats.chats[0].messages[0].errorMessage,'interrupted');}finally{reopened.close();}
});
test('memory-only upserts remain readable until the server stops',()=>{
 const memory=new Store(null);try{assert.equal(memory.upsertChat({id:'temporary',messages:[]},'temporary'),true);assert.equal(memory.state.chats.chats[0].id,'temporary');assert.equal(memory.db,null);}finally{memory.close();}
});
