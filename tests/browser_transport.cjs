/* Reproducible transport tests in Node; these do not claim a full browser E2E. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('apps/client.js', 'utf8');
function runtime({storage = {}, namespace = 'learner-en', fail = false, backup} = {}) {
  const sent = [];
  const messages = [];
  const elements = new Map();
  const localStorage = {
    getItem: key => storage[key] ?? null,
    setItem: (key, value) => { storage[key] = value; localStorage[key] = value; },
    removeItem: key => { delete storage[key]; delete localStorage[key]; }
  };
  for (const [key, value] of Object.entries(storage)) localStorage[key] = value;
  const node = () => ({style:{}, setAttribute(){}, replaceChildren(...content){ this.textContent = content.join(''); messages.push(this.textContent); }, append(){}, remove(){ elements.delete(this.id); }});
  const context = vm.createContext({
    window: {fetch: async (url, options) => {
      if (url === '/api/session') return {ok:true,json:async()=>({token:'csrf',namespace,locale:'ru'})};
      const body = JSON.parse(options.body); sent.push(body);
      if (fail) throw new Error('offline');
      return {ok:true,json:async()=>({ok:true,batch_id:body.batch_id,backup})};
    }},
    location:{origin:'http://localhost:8765',reload(){}}, localStorage,
    crypto:require('node:crypto').webcrypto,
    document:{documentElement:{},getElementById:id=>elements.get(id)||null,createElement:node,createTextNode:value=>value,body:{prepend(element){ elements.set(element.id,element); }}},
    Error, JSON, String, Object, encodeURIComponent
  });
  vm.runInContext(source, context);
  return {api:context.window.Tutor,sent,storage,messages,elements};
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
  const savedWithoutBackup = runtime({backup:{status:'unavailable'}});
  const acknowledgment = await savedWithoutBackup.api.post('/api/deck', {results:[{id:'one',grade:3}]});
  assert.equal(acknowledgment.ok,true);
  assert.equal(Object.keys(savedWithoutBackup.storage).length,0);
  assert.match(savedWithoutBackup.messages.at(-1),/Ответ сохранён.*Резервная копия недоступна/);
  savedWithoutBackup.api.status('Все показанные ответы сохранены.');
  assert.match(savedWithoutBackup.elements.get('backup-status').textContent,/Резервная копия недоступна/);
  console.log('Browser transport: 4 scenarios passed (concurrency, offline replay, learner isolation, backup warning)');
})().catch(error=>{ console.error(error);process.exitCode=1; });
