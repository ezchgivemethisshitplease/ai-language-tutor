/* Reproducible transport tests in Node; these do not claim a full browser E2E. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('apps/client.js', 'utf8');
function runtime({storage = {}, namespace = 'learner-en', fail = false} = {}) {
  const sent = [];
  const localStorage = {
    getItem: key => storage[key] ?? null,
    setItem: (key, value) => { storage[key] = value; localStorage[key] = value; },
    removeItem: key => { delete storage[key]; delete localStorage[key]; }
  };
  for (const [key, value] of Object.entries(storage)) localStorage[key] = value;
  const node = () => ({style:{}, setAttribute(){}, replaceChildren(){}, append(){}});
  const context = vm.createContext({
    window: {fetch: async (url, options) => {
      if (url === '/api/session') return {ok:true,json:async()=>({token:'csrf',namespace,locale:'ru'})};
      const body = JSON.parse(options.body); sent.push(body);
      if (fail) throw new Error('offline');
      return {ok:true,json:async()=>({ok:true,batch_id:body.batch_id})};
    }},
    location:{origin:'http://localhost:8765',reload(){}}, localStorage,
    crypto:require('node:crypto').webcrypto,
    document:{documentElement:{},getElementById:()=>null,createElement:node,createTextNode:value=>value,body:{prepend(){}}},
    Error, JSON, String, Object, encodeURIComponent
  });
  vm.runInContext(source, context);
  return {api:context.window.Tutor,sent,storage};
}
(async () => {
  const first = runtime();
  await Promise.all([
    first.api.post('/api/text', {addWord:'first'}),
    first.api.post('/api/text', {addWord:'second'})
  ]);
  assert.deepEqual(first.sent.map(item=>item.addWord), ['first','second']);
  assert.equal(Object.keys(first.storage).length, 0);
  assert.notEqual(first.sent[0].batch_id, first.sent[1].batch_id);
  const offline = runtime({fail:true});
  await assert.rejects(offline.api.post('/api/deck', {results:[{id:'one',grade:1}]}));
  assert.equal(Object.keys(offline.storage).length, 1);
  const recovered = runtime({storage:offline.storage});
  await recovered.api.flush();
  assert.equal(recovered.sent.length, 1);
  assert.equal(recovered.sent[0].results[0].grade, 1);
  assert.equal(Object.keys(recovered.storage).length, 0);
  const other = runtime({fail:true});
  await assert.rejects(other.api.post('/api/deck', {results:[]}));
  const differentLearner = runtime({storage:other.storage,namespace:'different-learner'});
  await differentLearner.api.flush();
  assert.equal(differentLearner.sent.length,0);
  assert.equal(Object.keys(differentLearner.storage).length,1);
  console.log('Browser transport: 3 scenarios passed (concurrency, offline replay, learner isolation)');
})().catch(error=>{ console.error(error);process.exitCode=1; });
