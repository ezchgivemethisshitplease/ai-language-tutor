/* Deterministic permission/recorder/transport probes; no microphone or real voice is used. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../apps/speech.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

class Element {
  constructor() {
    this.hidden = false; this.disabled = false; this.value = ''; this.textContent = '';
    this.attributes = {}; this.handlers = {}; this.classes = new Set(); this.pauses = 0;
    this.classList = {toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name)};
  }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  removeAttribute(key) { delete this.attributes[key]; if (key === 'src') delete this.src; }
  addEventListener(type, handler) { (this.handlers[type] ||= []).push(handler); }
  async fire(type, event = {}) { await Promise.all((this.handlers[type] || []).map(handler => handler(event))); await tick(); }
  pause() { this.pauses += 1; }
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

async function runtime({draft = '', permission = 'granted', fail = false, hold = null,
  audioBytes = 8, transcript = 'I went to the library.', status = 'ready', remoteVoices = false} = {}) {
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  get('speech-language').value = 'auto'; get('speech-read-language').value = 'auto';
  const requests = [], recorders = [], revoked = [], utterances = [], notices = [];
  const timers = new Map(), intervals = new Map(); let nextTimer = 0, mediaCalls = 0, stopped = 0;
  let current = {text:draft, context:'conversation-one', revision:0};
  let offline = fail, currentStatus = status;
  const track = {stop() { stopped += 1; }};
  const stream = {getTracks: () => [track]};
  const permissionRequest = permission === 'pending' ? deferred() : null;
  class Recorder {
    static isTypeSupported(type) { return type.startsWith('audio/webm'); }
    constructor(_, options) { this.mimeType = options?.mimeType || 'audio/webm'; this.state = 'inactive'; this.handlers = {}; recorders.push(this); }
    addEventListener(type, handler) { (this.handlers[type] ||= []).push(handler); }
    emit(type, event = {}) { for (const handler of this.handlers[type] || []) handler(event); }
    start(timeslice) { this.state = 'recording'; this.timeslice = timeslice; }
    stop() {
      if (this.state === 'inactive') throw new Error('Already stopped');
      this.state = 'inactive';
      queueMicrotask(() => { this.emit('dataavailable', {data:new Blob([new Uint8Array(audioBytes)], {type:this.mimeType})}); this.emit('stop'); });
    }
  }
  const localUrl = class extends URL {};
  localUrl.createObjectURL = () => 'blob:local-test';
  localUrl.revokeObjectURL = url => revoked.push(url);
  const result = () => ({text:transcript, language:'en', duration_seconds:1, backend:'whisper.cpp', model:'base', evidence_policy:'transcript_only'});
  const request = async (route, options = {}) => {
    requests.push({route, options});
    if (route === '/api/speech/status') return {json:async () => ({status:currentStatus,available:currentStatus === 'ready',max_seconds:60,max_bytes:12 * 1024 * 1024,accepted_mime_types:['audio/webm','audio/ogg','audio/mp4'],setup_available:true,setup_command:'python tools/speech.py setup'})};
    if (route === '/api/speech/setup') return {json:async () => ({accepted:true})};
    if (route === '/api/speech/transcribe') {
      if (offline) throw new Error('Network unavailable');
      if (hold) {
        options.signal.addEventListener('abort', () => { const error = new Error('Aborted'); error.name = 'AbortError'; hold.reject(error); }, {once:true});
        await hold.promise;
      }
      return {json:async () => result()};
    }
    throw new Error(`Unexpected route ${route}`);
  };
  class Utterance { constructor(text) { this.text = text; } }
  const context = vm.createContext({
    window:{MediaRecorder:Recorder,isSecureContext:true,SpeechSynthesisUtterance:Utterance,
      speechSynthesis:{cancel(){},getVoices:() => [{lang:'en-US',localService:!remoteVoices},{lang:'ru-RU',localService:!remoteVoices}],speak(utterance){utterances.push(utterance);queueMicrotask(() => utterance.onend?.());}}},
    navigator:{mediaDevices:{getUserMedia:async () => {
      mediaCalls += 1;
      if (permission === 'denied') { const error = new Error('Denied'); error.name = 'NotAllowedError'; throw error; }
      return permissionRequest ? permissionRequest.promise : stream;
    }}},
    document:{getElementById:get},Blob,URL:localUrl,AbortController,Date,Number,String,Map,Set,Array,Object,Error,
    setTimeout:(fn,delay) => { const id = ++nextTimer;timers.set(id,{fn,delay});return id; },
    clearTimeout:id => timers.delete(id),
    setInterval:(fn,delay) => { const id = ++nextTimer;intervals.set(id,{fn,delay});return id; },
    clearInterval:id => intervals.delete(id)
  });
  vm.runInContext(source, context);
  const controller = context.window.TutorSpeech.create({request, getDraft:() => ({...current}),
    applyDraft(text, {mode, snapshot}) {
      if (mode === 'if-empty' && (current.text !== '' || snapshot.context !== current.context || snapshot.revision !== current.revision)) return false;
      const combined = mode === 'append' && current.text ? `${current.text}\n${text}` : text;
      if (combined.length > 16000) return false;
      current = {...current,text:combined,revision:current.revision + 1}; return true;
    },notice:text => notices.push(text)});
  await controller.ready; controller.setComposerAvailable(true);
  return {controller,get,requests,recorders,revoked,utterances,notices,timers,intervals,
    get draft() { return current.text; },get mediaCalls() { return mediaCalls; },get stopped() { return stopped; },
    online() { offline = false; },setDraft(text) { current = {...current,text,revision:current.revision + 1}; },
    switchConversation() { current = {text:'',context:'conversation-two',revision:current.revision + 1}; },
    resolvePermission() { permissionRequest.resolve(stream); },setStatus(value) { currentStatus = value; }};
}

(async () => {
  const success = await runtime();
  assert.equal(success.mediaCalls, 0, 'Loading the page must not request microphone permission');
  assert.equal(success.requests.filter(r => r.route === '/api/speech/setup').length, 0);
  await success.get('speech-record').fire('click');
  assert.equal(success.mediaCalls, 1); assert.equal(success.recorders[0].state, 'recording');
  assert.equal(success.get('speech-timer').textContent, '00:00');
  await success.get('speech-stop').fire('click'); await tick();
  assert.equal(success.draft, 'I went to the library.'); assert.equal(success.stopped, 1);
  const upload = success.requests.find(r => r.route === '/api/speech/transcribe');
  assert(upload.options.body instanceof Blob); assert.match(upload.options.headers['Content-Type'], /^audio\/webm/);
  assert.equal(upload.options.headers['X-Speech-Language'], 'auto');
  assert.equal(success.requests.filter(r => r.route.includes('/api/web/chat')).length, 0);
  assert.deepEqual(success.revoked, ['blob:local-test']);
  assert.equal(success.intervals.size, 0);

  const cancelled = await runtime({draft:'Original draft'});
  await cancelled.get('speech-record').fire('click'); await cancelled.get('speech-cancel').fire('click'); await tick();
  assert.equal(cancelled.draft, 'Original draft'); assert.equal(cancelled.stopped, 1);
  assert.equal(cancelled.requests.filter(r => r.route === '/api/speech/transcribe').length, 0);
  assert.equal(cancelled.get('speech-panel').hidden, true);

  const denied = await runtime({permission:'denied', draft:'Still typed'});
  await denied.get('speech-record').fire('click');
  assert.equal(denied.draft, 'Still typed'); assert.match(denied.get('speech-status').textContent, /не разрешён/);
  assert.equal(denied.requests.filter(r => r.route === '/api/speech/transcribe').length, 0);

  const latePermission = await runtime({permission:'pending'});
  const starting = latePermission.get('speech-record').fire('click');
  await latePermission.get('speech-cancel').fire('click'); latePermission.resolvePermission(); await starting; await tick();
  assert.equal(latePermission.recorders.length, 0); assert.equal(latePermission.stopped, 1);

  const original = await runtime({draft:'Do not replace me.'});
  await original.get('speech-record').fire('click'); await original.get('speech-stop').fire('click'); await tick();
  assert.equal(original.draft, 'Do not replace me.'); assert.equal(original.get('speech-result').hidden, false);
  original.get('speech-transcript').value = 'An edited transcription.';
  await original.get('speech-append').fire('click');
  assert.equal(original.draft, 'Do not replace me.\nAn edited transcription.');

  const inference = deferred(); const edited = await runtime({hold:inference});
  await edited.get('speech-record').fire('click'); await edited.get('speech-stop').fire('click'); await tick();
  edited.setDraft('Typed while recognition was running.'); inference.resolve(); await tick();
  assert.equal(edited.draft, 'Typed while recognition was running.'); assert.equal(edited.get('speech-result').hidden, false);

  const changing = deferred(); const switched = await runtime({hold:changing});
  await switched.get('speech-record').fire('click'); await switched.get('speech-stop').fire('click'); await tick();
  switched.switchConversation(); changing.resolve(); await tick();
  assert.equal(switched.draft, ''); assert.equal(switched.get('speech-result').hidden, false);

  const retry = await runtime({fail:true,draft:'Preserved during network failure.'});
  await retry.get('speech-record').fire('click'); await retry.get('speech-stop').fire('click'); await tick();
  assert.equal(retry.draft, 'Preserved during network failure.'); assert.equal(retry.get('speech-retry').hidden, false);
  assert.equal(retry.revoked.length, 0, 'Keep the recorded Blob until acknowledgment or cancellation');
  const firstBlob = retry.requests.find(r => r.route === '/api/speech/transcribe').options.body;
  retry.online(); await retry.get('speech-retry').fire('click'); await tick();
  const uploads = retry.requests.filter(r => r.route === '/api/speech/transcribe');
  assert.equal(uploads.length, 2); assert.equal(uploads[1].options.body, firstBlob); assert.equal(retry.revoked.length, 1);

  const empty = await runtime({transcript:'  ',draft:'Keep this.'});
  await empty.get('speech-record').fire('click'); await empty.get('speech-stop').fire('click'); await tick();
  assert.equal(empty.draft, 'Keep this.'); assert.equal(empty.get('speech-retry').hidden, false);
  await empty.get('speech-cancel').fire('click'); assert.equal(empty.revoked.length, 1);

  const bounded = await runtime(); await bounded.get('speech-record').fire('click');
  const deadline = [...bounded.timers.values()].find(timer => timer.delay === 59700);
  assert(deadline, 'Recording needs a bounded deadline'); deadline.fn(); await tick();
  assert.equal(bounded.stopped, 1); assert.equal(bounded.draft, 'I went to the library.');

  const speaking = await runtime(); let playing = false;
  speaking.controller.speak('После `did` нужен глагол.\nI went home.', value => { playing = value; }); await tick();
  assert(speaking.utterances.some(utterance => utterance.lang === 'ru-RU'));
  assert(speaking.utterances.some(utterance => utterance.lang === 'en-US'));
  assert.equal(playing, false); assert.equal(speaking.mediaCalls, 0);
  speaking.controller.dispose();
  const remote = await runtime({remoteVoices:true}); remote.controller.speak('Do not send this to a remote voice.');
  assert.equal(remote.utterances.length, 0); assert.match(remote.notices[0], /локальный голос/);

  const tooLarge = await runtime({audioBytes:13 * 1024 * 1024, draft:'Keep this draft.'});
  await tooLarge.get('speech-record').fire('click'); await tooLarge.get('speech-stop').fire('click');
  assert.equal(tooLarge.requests.filter(r => r.route === '/api/speech/transcribe').length, 0);
  assert.equal(tooLarge.draft, 'Keep this draft.'); assert.match(tooLarge.get('speech-status').textContent, /слишком большая/);

  const aborting = deferred(); const aborted = await runtime({hold:aborting, draft:'Safe.'});
  await aborted.get('speech-record').fire('click'); await aborted.get('speech-stop').fire('click');
  await aborted.get('speech-cancel').fire('click'); await tick();
  assert.equal(aborted.draft, 'Safe.'); assert.equal(aborted.revoked.length, 1); assert.equal(aborted.get('speech-panel').hidden, true);

  const unavailable = await runtime({status:'unavailable', draft:'Typed fallback.'});
  await unavailable.get('speech-record').fire('click'); assert.equal(unavailable.mediaCalls, 0);
  assert.equal(unavailable.requests.filter(r => r.route === '/api/speech/setup').length, 0);
  await unavailable.get('speech-setup').fire('click');
  assert.equal(unavailable.requests.filter(r => r.route === '/api/speech/setup').length, 1);
  assert.equal(unavailable.draft, 'Typed fallback.'); assert.equal(unavailable.mediaCalls, 0);

  const noFeedbackLoop = await runtime(); await noFeedbackLoop.get('speech-record').fire('click');
  noFeedbackLoop.controller.speak('Do not play into the live microphone.');
  assert.equal(noFeedbackLoop.utterances.length, 0); await noFeedbackLoop.get('speech-cancel').fire('click');
  console.log('Speech UI: 16 scenarios passed (explicit permission, cancellation, denial, late permission, preserved draft, inference edits, conversation change, Blob retry, empty result, recording deadline, mixed-language read-aloud, local voices only, byte limit, inference cancellation, explicit setup, no feedback loop).');
})().catch(error => { console.error(error); process.exitCode = 1; });
