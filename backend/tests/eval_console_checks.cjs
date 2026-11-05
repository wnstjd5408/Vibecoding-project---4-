// Browser event logic with no network or dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = Object.fromEntries(['bundle','preflight','status','D01','D02','D03','download','notice','output']
  .map(id => [id, {disabled:false, textContent:'', files:[]}]));
let calls = [], responder, downloaded = false;
const context = {
  document: {getElementById:id=>nodes[id], createElement:()=>({click(){downloaded=true;}})},
  fetch: async (url, options) => {calls.push({url,options}); return responder();},
  Blob, URL: {createObjectURL:()=> 'blob:fixture',revokeObjectURL:()=>{}}
};
vm.runInNewContext(fs.readFileSync('evals/console.js','utf8'), context);
(async () => {
  assert.equal(calls.length,0);
  assert(nodes.D01.disabled);
  nodes.bundle.files=[{size:40,text:async()=>JSON.stringify({cases:[],manifest:{},config:{}})}];
  await nodes.bundle.onchange();
  assert.equal(calls.length,0);
  await nodes.D01.onclick(); // Cannot run before preflight.
  assert.equal(calls.length,0);
  responder=async()=>({ok:true,json:async()=>({ready:true,next_slot:'D01'})});
  await nodes.preflight.onclick();
  assert.equal(nodes.D01.disabled,false);
  assert(nodes.D02.disabled);
  let finish;
  responder=()=>new Promise(resolve=>{finish=resolve;});
  const active=nodes.D01.onclick();
  await nodes.D01.onclick();
  await nodes.status.onclick();
  assert.equal(calls.length,2); // preflight + exactly one run
  const payload={slots:{D01:{text:'<img src=x onerror=alert(1)>'}}};
  finish({ok:true,json:async()=>payload});
  await active;
  assert(nodes.output.textContent.includes('<img'));
  assert.equal(nodes.output.innerHTML,undefined);
  assert(nodes.D02.disabled); // New preflight required.
  nodes.download.onclick(); assert(downloaded);
  responder=async()=>{throw new Error('network failure');};
  await nodes.preflight.onclick();
  assert.equal(calls.length,3); // No automatic retry
  assert(nodes.D01.disabled && nodes.D02.disabled && nodes.D03.disabled);
  assert.equal(calls[1].options.credentials,'same-origin');
  assert.equal(calls[1].options.redirect,'error');
  console.log('console event checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
