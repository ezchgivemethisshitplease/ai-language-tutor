/* UI transport/rendering probes with a deliberately small DOM, not browser E2E. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../apps/chat.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../apps/chat.html'), 'utf8');
class Element {
  constructor(tag='div') { this.tagName=tag;this.children=[];this._text='';this.attributes={};this.dataset={};this.style={};this.handlers={};this.hidden=false;this.disabled=false;this.value='';this.scrollTop=0;this.scrollHeight=200;this.clientHeight=200;this.className='';this.classList={contains:n=>this.className.split(' ').includes(n),add:n=>{if(!this.classList.contains(n))this.className+=' '+n;},remove:n=>{this.className=this.className.split(' ').filter(x=>x!==n).join(' ');},toggle:(n,force)=>{const use=force??!this.classList.contains(n);use?this.classList.add(n):this.classList.remove(n);return use;}};}
  set innerHTML(_) { throw new Error('Untrusted HTML insertion is forbidden'); }
  get innerHTML() { throw new Error('HTML parsing is not supported'); }
  set textContent(text) { this._text=String(text);this.children=[]; }
  get textContent() { return this._text+this.children.map(x=>x.textContent||'').join(''); }
  get childNodes(){return this.children;}
  get firstChild(){return this.children[0];}
  append(...nodes){for(const n of nodes){if(n.tagName==='#fragment'){this.append(...n.children);n.children=[];}else{n.remove();this.children.push(n);n.parentNode=this;}}}
  replaceChildren(...nodes){this.children=[];this._text='';this.append(...nodes);}
  setAttribute(k,v){this.attributes[k]=String(v);}
  removeAttribute(k){delete this.attributes[k];}
  addEventListener(type,fn){(this.handlers[type]??=[]).push(fn);}
  focus(){} remove(){if(this.parentNode){this.parentNode.children=this.parentNode.children.filter(x=>x!==this);this.parentNode=null;}} click(){return this.fire('click');} showModal(){this.open=true;} close(){this.open=false;} reportValidity(){return true;}
  fire(type,event={}){return Promise.all((this.handlers[type]||[]).map(fn=>fn({preventDefault(){},...event})));}
}
async function runtime({namespace='one',storage={},auth='chatgpt',existing=null,offline=false,loginUrl='https://auth.openai.com/deviceauth',backup='disabled',speech=false,url='http://localhost:8765/chat.html',personalization=null}={}){
 const elements=new Map();
 for(const match of html.matchAll(/<([\w-]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){const e=new Element(match[1]);e.id=match[3];for(const d of match[2].matchAll(/data-([\w-]+)="([^"]*)"/g))e.dataset[d[1].replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]=d[2];elements.set(e.id,e);}
 const get=id=>elements.get(id);const requests=[];const timers=new Map();let timer=0;let fail=offline;let events=[];let backupStatus=backup;let speechOptions=null;let conflict=false;
 let conversation=existing||{id:'conv-one',title:'A saved conversation',messages:[{id:'u1',role:'user',text:'<img src=x onerror=alert(1)>'},{id:'a1',role:'assistant',text:'Exact reply <script>alert(2)</script> [Упражнение](quiz.html) https://example.org/reference. [bad](javascript:alert(1))'}],cursor:2,active:false,turn_id:'turn-one'};
 const personal=personalization||{revision:1,account_preferences:{dialect:'us',register:'informal',explanation_language:'native',explanation_style:'plain',grammar_terminology:'minimal',correction_style:'balanced',topics:[],notes:''},directions:[{id:'work',title:'Английский для работы',description:'Рабочие ситуации',goal:'Обсудить задачу с коллегой',topics:['работа'],mode:'roleplay',scenario:'Вы коллега',register:'professional'}],memories:[],pending_memories:[]};
 const status=()=>({backup:{status:backupStatus},personalization:personal,initialized:true,profile:{daily_minutes:20,voice_channel:'none'},auth:{status:auth},models:[{id:'model-one',displayName:'One'}],conversations:existing?[{id:conversation.id,title:conversation.title}]:[],active_conversation_id:existing?conversation.id:null});
 const context=vm.createContext({document:{getElementById:get,body:new Element('body'),hidden:false,createElement:t=>new Element(t),createDocumentFragment:()=>new Element('#fragment'),querySelector:()=>new Element('main'),querySelectorAll:selector=>[...elements.values()].filter(e=>selector==='[data-prompt]'?'prompt'in e.dataset:'sessionAction'in e.dataset),addEventListener(){}},window:{...(speech?{TutorSpeech:{create(options){speechOptions=options;return{setComposerAvailable(){},canSpeak:()=>false,stopSpeaking(){},dispose(){}};}}}:{}),matchMedia:()=>({matches:false}),addEventListener(){}},Tutor:{ready:Promise.resolve({namespace,token:'token'}),request:async(path,options={})=>{requests.push({path,options});let data;if(path==='/api/web/status')data=status();else if(path==='/api/web/personalization')data=personal;else if(path==='/api/web/preferences'){if(conflict){const error=new Error('revision');error.status=409;throw error;}Object.assign(personal.account_preferences,JSON.parse(options.body).preferences);personal.revision++;data={ok:true,...personal};}else if(path==='/api/web/conversations'){conversation={id:'conv-new',title:'Новое занятие',messages:[],cursor:0,active:false,context:JSON.parse(options.body).context};data=conversation;}else if(path==='/api/web/context'){if(conflict){const error=new Error('revision');error.status=409;throw error;}conversation.context=JSON.parse(options.body).context;personal.revision++;data={ok:true,context:conversation.context,revision:personal.revision};}else if(path==='/api/web/memory'){const body=JSON.parse(options.body);if(body.action==='confirm'){const item=personal.pending_memories.find(item=>item.id===body.id);personal.memories.push(item);personal.pending_memories=personal.pending_memories.filter(item=>item.id!==body.id);}else if(body.action==='dismiss')personal.pending_memories=personal.pending_memories.filter(item=>item.id!==body.id);else if(body.action==='delete')personal.memories=personal.memories.filter(item=>item.id!==body.id);else{personal.memories=personal.memories.filter(item=>item.id!==body.id);personal.memories.push({id:body.id||'manual-memory',text:body.text,scope:body.scope,conversation_id:body.conversation_id});}personal.revision++;data={ok:true,...personal};}else if(path==='/api/web/session'){const body=JSON.parse(options.body);if(body.action==='handoff')conversation.lesson={...conversation.lesson,owned:true,can_manage:true,requires_handoff:false,owner:{conversation_id:conversation.id,title:conversation.title}};data=status();}else if(path.startsWith('/api/web/conversation?'))data=conversation;else if(path.startsWith('/api/web/events'))data={events:events.filter(e=>e.seq>Number(new URL(path,'http://localhost:8765').searchParams.get('after'))),cursor:Math.max(conversation.cursor,...events.map(e=>e.seq)),active:conversation.active};else if(path==='/api/web/chat'){if(fail)throw new Error('offline');data={conversation_id:conversation.id,turn_id:null,accepted:true,request_id:JSON.parse(options.body).request_id};}else if(path==='/api/web/interrupt'){data={ok:true};}else if(path==='/api/web/login')data={auth_url:loginUrl,login_id:'login-one'};else throw new Error(path);return{json:async()=>data};}},location:{origin:'http://localhost:8765',href:url,reload(){}},localStorage:{getItem:k=>storage[k]??null,setItem:(k,v)=>{storage[k]=String(v);},removeItem:k=>{delete storage[k];}},crypto:require('node:crypto').webcrypto,navigator:{clipboard:{writeText:async()=>{}}},setTimeout:(fn,delay)=>{const id=++timer;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id),setInterval:()=>0,AbortController,URL,Intl,Date,Map,Set,Number,String,JSON,Array,Object,Promise,Error,structuredClone,encodeURIComponent});
 vm.runInContext(source,context);await context.window.TutorChatReady;
 return{context,get,requests,storage,timers,personal,setConflict:value=>{conflict=value;},online(){fail=false;},tick:()=>new Promise(resolve=>setImmediate(resolve)),setConversation:c=>{conversation=c;},setEvents:e=>{events=e;},setBackup:value=>{backupStatus=value;},applySpeech:text=>speechOptions.applyDraft(text,{mode:'append'}),runPoll:async()=>{const entry=[...timers.entries()].find(([,value])=>value.delay<=5000);assert(entry,'A poll should be scheduled');timers.delete(entry[0]);await entry[1].fn();}};
}
(async()=>{
 const shared={};const first=await runtime({storage:shared,offline:true});
 first.get('message-input').value='  A draft with <script>not markup</script>\n';
 await first.get('message-input').fire('input');await first.get('chat-form').fire('submit');await first.tick();
 const firstPost=first.requests.find(x=>x.path==='/api/web/chat');assert(firstPost);const payload=JSON.parse(firstPost.options.body);assert.equal(payload.message,'  A draft with <script>not markup</script>\n');assert.equal(first.get('pending-notice').hidden,false);assert(Object.keys(shared).some(k=>k.endsWith(':pending')));
 const isolated=await runtime({namespace:'two',storage:shared});assert.equal(isolated.get('message-input').value,'');assert.equal(isolated.requests.filter(x=>x.path==='/api/web/chat').length,0);
 first.online();await first.get('retry-message').fire('click');await first.tick();await first.tick();const posts=first.requests.filter(x=>x.path==='/api/web/chat');assert.equal(posts.length,2);assert.equal(JSON.parse(posts[1].options.body).request_id,payload.request_id);assert(!Object.keys(shared).some(k=>k.endsWith(':pending')));assert.match(first.get('messages').textContent,/<img src=x onerror=alert\(1\)>/);assert.match(first.get('messages').textContent,/<script>alert\(2\)<\/script>/);
 const disconnected=await runtime({auth:'unauthenticated',loginUrl:'javascript:alert(1)'});assert.equal(disconnected.get('message-input').disabled,true);await disconnected.get('login-button').fire('click');assert.equal(disconnected.get('login-link').href,undefined);assert.equal(disconnected.get('notice').hidden,false);
 const connected=await runtime({auth:'unauthenticated'});await connected.get('login-button').fire('click');assert.equal(connected.get('login-link').href,'https://auth.openai.com/deviceauth');assert.equal(connected.get('login-link').hidden,false);

 const descendants=e=>[e,...e.children.flatMap(descendants)];
 const links=descendants(first.get('messages')).filter(e=>e.tagName==='a');
 assert.deepEqual(links.map(e=>e.href),['http://localhost:8765/quiz.html','https://example.org/reference']);
 assert.equal(links[1].rel,'noopener noreferrer');
 const snapshot={id:'stream',title:'Streaming',messages:[{id:'stream-a',role:'assistant',text:'Hello'}],cursor:2,active:true,turn_id:'t-stream'};
 const streaming=await runtime({existing:snapshot});
 const firstArticle=streaming.get('messages').children[0];
 streaming.setEvents([{seq:3,type:'delta',message_id:'stream-a',role:'assistant',text:' world'}]);
 streaming.setConversation({...snapshot,cursor:3,messages:[{id:'stream-a',role:'assistant',text:'Hello world'}]});
 await streaming.runPoll();
 assert.equal(streaming.get('messages').children[0],firstArticle,'Streaming must preserve existing message nodes');
 assert.match(streaming.get('messages').textContent,/Hello world/);
 assert(!streaming.get('messages').textContent.includes('HelloHello'));
 await streaming.get('stop-button').fire('click');
 assert.equal(streaming.requests.filter(x=>x.path==='/api/web/interrupt').length,1);
 streaming.setEvents([{seq:4,type:'turn_completed',turn_id:'t-stream',status:'interrupted'}]);
 streaming.setConversation({...snapshot,cursor:4,active:false,messages:[{id:'stream-a',role:'assistant',text:'Hello world'}]});
 await streaming.runPoll();
 assert.equal(streaming.get('stop-button').hidden,true);
 assert.equal(streaming.get('messages').children.length,1);
 assert.equal(streaming.get('messages').children[0],firstArticle,'Resume must retain the same immutable message identity');
 const unsafe=await runtime({auth:'unauthenticated',loginUrl:'https://auth.openai.com.evil.example/device'});
 await unsafe.get('login-button').fire('click');assert.equal(unsafe.get('login-link').href,undefined);
 assert.equal(html.includes('maxlength="16000"'),true);

 const warned=await runtime({backup:'warning',offline:true});
 assert.equal(warned.get('backup-warning').hidden,false);
 warned.get('message-input').value='A saved answer while the backup disk is missing.';
 await warned.get('chat-form').fire('submit');await warned.tick();
 assert.equal(warned.get('backup-warning').hidden,false,'A chat error must not replace the backup warning');
 warned.online();await warned.get('retry-message').fire('click');await warned.tick();
 warned.setEvents([{seq:3,type:'turn_completed',turn_id:'finished',status:'completed'}]);
 warned.setConversation({id:'conv-one',title:'Saved',messages:[],cursor:3,active:false,turn_id:'finished'});
 await warned.runPoll();await warned.tick();
 assert.equal(warned.get('backup-warning').hidden,false,'Turn completion must not clear an unresolved backup warning');
 warned.setBackup('unknown-future-status');await warned.get('refresh-history').fire('click');
 assert.equal(warned.get('backup-warning').hidden,false,'An unknown status must not hide an existing warning');
 warned.setBackup('not_due');await warned.get('refresh-history').fire('click');assert.equal(warned.get('backup-warning').hidden,true);
 warned.setBackup('unavailable');await warned.get('refresh-history').fire('click');assert.equal(warned.get('backup-warning').hidden,false);
 warned.setBackup('disabled');await warned.get('refresh-history').fire('click');assert.equal(warned.get('backup-warning').hidden,true);

 const speechStorage={}; const dictated=await runtime({speech:true,offline:true,storage:speechStorage});
 assert.equal(dictated.applySpeech('A spoken answer.'),true);
 dictated.get('message-input').value='A spoken answer, edited.';await dictated.get('message-input').fire('input');
 await dictated.get('chat-form').fire('submit');await dictated.tick();
 const voiceRequest=JSON.parse(dictated.requests.find(r=>r.path==='/api/web/chat').options.body);
 assert.equal(voiceRequest.input_source,'whisper_transcript');
 const recoveredVoice=await runtime({speech:true,storage:speechStorage});
 assert.equal(recoveredVoice.get('message-input').value,'A spoken answer, edited.');
 assert.equal(recoveredVoice.requests.filter(r=>r.path==='/api/web/chat').length,0);
 await recoveredVoice.get('retry-message').fire('click');await recoveredVoice.tick();
 const voiceRetry=JSON.parse(recoveredVoice.requests.find(r=>r.path==='/api/web/chat').options.body);
 assert.equal(voiceRetry.input_source,'whisper_transcript');assert.equal(voiceRetry.request_id,voiceRequest.request_id);
 recoveredVoice.get('message-input').value='';await recoveredVoice.get('message-input').fire('input');
 recoveredVoice.get('message-input').value='An independently typed answer.';await recoveredVoice.get('message-input').fire('input');
 await recoveredVoice.get('chat-form').fire('submit');await recoveredVoice.tick();
 const typedRequest=JSON.parse(recoveredVoice.requests.filter(r=>r.path==='/api/web/chat').at(-1).options.body);
 assert.equal(typedRequest.input_source,'typed');
 const preferred=await runtime({url:'http://localhost:8765/chat.html?settings=1'});
 assert.equal(preferred.get('preferences-dialog').open,true);
 assert.equal(preferred.get('pref-dialect').value,'us');assert.equal(preferred.get('pref-register').value,'informal');
 preferred.get('pref-register').value='professional';preferred.get('pref-explanation-style').value='detailed';preferred.get('pref-topics').value='Films\nTravel';preferred.get('pref-notes').value='<script>literal preference</script>';
 await preferred.get('preferences-form').fire('submit');
 const preferencePost=JSON.parse(preferred.requests.find(item=>item.path==='/api/web/preferences').options.body);
 assert.equal(preferencePost.expected_revision,1);assert.deepEqual(preferencePost.preferences.topics,['Films','Travel']);assert.equal(preferencePost.preferences.notes,'<script>literal preference</script>');
 assert.equal(preferred.get('preferences-success').hidden,false);
 const preferenceReload=await runtime({personalization:preferred.personal});await preferenceReload.get('open-preferences').fire('click');
 assert.equal(preferenceReload.get('pref-register').value,'professional');assert.equal(preferenceReload.get('pref-notes').value,'<script>literal preference</script>');
 assert.match(preferenceReload.get('context-summary').textContent,/Деловое общение/);
 preferenceReload.setConflict(true);preferenceReload.get('pref-notes').value='Keep this unsaved edit';await preferenceReload.get('preferences-form').fire('submit');
 assert.equal(preferenceReload.get('pref-notes').value,'Keep this unsaved edit');assert.match(preferenceReload.get('preferences-error').textContent,/другой вкладке/);

 const contextual=await runtime({url:'http://localhost:8765/chat.html?new=1&direction=work',offline:true});
 assert.match(contextual.get('context-goal').textContent,/Обсудить задачу/);assert.match(contextual.get('context-summary').textContent,/Деловое общение/);
 assert.equal(contextual.requests.filter(item=>item.path==='/api/web/chat'||item.path==='/api/web/conversations').length,0,'Direction links must not start inference or create a chat');
 contextual.get('message-input').value='My exact answer  \n';await contextual.get('message-input').fire('input');await contextual.get('chat-form').fire('submit');await contextual.tick();
 const contextReceipt=JSON.parse(contextual.requests.find(item=>item.path==='/api/web/chat').options.body);
 assert.equal(contextReceipt.context.direction_id,'work');assert.equal(contextReceipt.context.register,'professional');
 contextual.personal.directions[0].goal='A different future goal';contextual.online();await contextual.get('retry-message').fire('click');await contextual.tick();
 const contextRetry=JSON.parse(contextual.requests.filter(item=>item.path==='/api/web/chat').at(-1).options.body);
 assert.deepEqual(contextRetry.context,contextReceipt.context,'Retry must keep the original context snapshot');assert.equal(contextRetry.message,'My exact answer  \n');

 const ownContext={id:'lesson-context',title:'Работа',messages:[],cursor:0,active:false,context:{title:'Коллеги',goal:'Discuss a deadline',mode:'roleplay',register:'professional',challenge:'easy'},current_exercise:{exercise_id:'one',learner_view:{prompt:'What would you say?',context:'You need another day.'},answered:false}};
 const editor=await runtime({existing:ownContext});
 assert.match(editor.get('context-summary').textContent,/Деловое общение/);assert.equal(editor.get('current-task-prompt').textContent,'What would you say?');
 editor.get('message-input').value='Draft survives context edits';await editor.get('message-input').fire('input');
 await editor.get('edit-context').fire('click');editor.get('context-name').value='<b>Trip</b>';editor.get('context-goal-input').value='Order lunch';editor.get('context-register').value='';editor.get('context-mode').value='conversation';await editor.get('context-form').fire('submit');
 assert.equal(editor.get('conversation-title').textContent,'<b>Trip</b>');assert.match(editor.get('context-summary').textContent,/Неформальное общение/);assert.equal(editor.get('message-input').value,'Draft survives context edits');
 const contextPatch=JSON.parse(editor.requests.find(item=>item.path==='/api/web/context').options.body);assert.equal(contextPatch.conversation_id,'lesson-context');assert.equal(contextPatch.context.register,null);
 assert.equal(editor.requests.filter(item=>item.path==='/api/web/chat').length,0);
 const noOverrides=await runtime({existing:{...ownContext,id:'other',context:{goal:'Just talking',mode:'conversation'}}});assert.match(noOverrides.get('context-summary').textContent,/Неформальное общение/,'Overrides must not leak into another chat');
 const emptyEditor=await runtime({speech:true});emptyEditor.applySpeech('Spoken draft');await emptyEditor.get('edit-context').fire('click');emptyEditor.get('context-goal-input').value='Have lunch';await emptyEditor.get('context-form').fire('submit');
 assert.equal(emptyEditor.get('message-input').value,'Spoken draft');assert.equal(emptyEditor.requests.filter(item=>item.path==='/api/web/conversations').length,1);assert.equal(emptyEditor.requests.filter(item=>item.path==='/api/web/chat').length,0);
 await emptyEditor.get('chat-form').fire('submit');await emptyEditor.tick();assert.equal(JSON.parse(emptyEditor.requests.find(item=>item.path==='/api/web/chat').options.body).input_source,'whisper_transcript');

 const proposed={revision:1,account_preferences:{},directions:[],memories:[{id:'chat-memory',text:'Only for another chat',scope:'conversation',conversation_id:'other'}],pending_memories:[{id:'proposal-one',text:'I prefer practical examples.',scope:'account',source:{evidence:'Please remember practical examples.'}}]};
 const memory=await runtime({personalization:proposed});
 assert.equal(memory.requests.filter(item=>item.path==='/api/web/memory').length,0,'Proposals require a user action');assert(!memory.get('active-memories').textContent.includes('Only for another chat'));
 const confirm=descendants(memory.get('memory-proposals')).find(item=>item.tagName==='button'&&item.textContent==='Запомнить');assert(confirm);await confirm.fire('click');
 assert.equal(memory.personal.pending_memories.length,0);assert.equal(memory.personal.memories.length,2);assert.match(memory.get('active-memories').textContent,/practical examples/);
 const remove=descendants(memory.get('memory-list')).filter(item=>item.tagName==='button'&&item.textContent==='Удалить заметку').at(-1);await remove.fire('click');
 assert(!memory.get('active-memories').textContent.includes('practical examples'));assert.equal(JSON.parse(memory.requests.filter(item=>item.path==='/api/web/memory').at(-1).options.body).action,'delete');
 assert(html.includes('Удаление записи не удаляет исходные сообщения.'));

 const sharedLesson={...ownContext,id:'second-chat',lesson:{session:null,owned:false,can_manage:false,requires_handoff:true,owner:{conversation_id:'original-chat',title:'Первое занятие'},active_session_id:'same-plan'}};
 const handoff=await runtime({existing:sharedLesson});
 assert.equal(handoff.get('shared-session-notice').hidden,false);assert.equal(handoff.get('finish-session').disabled,true);assert.equal(handoff.get('shared-session-link').href,'chat.html?conversation=original-chat');
 await handoff.get('finish-session').fire('click');assert.equal(handoff.requests.filter(item=>item.path==='/api/web/session').length,0,'Another chat cannot finish the owned session');
 await handoff.get('handoff-session').fire('click');
 const claim=JSON.parse(handoff.requests.find(item=>item.path==='/api/web/session').options.body);assert.equal(claim.action,'handoff');assert.equal(claim.conversation_id,'second-chat');assert.equal(claim.expected_owner,'original-chat');assert.equal(handoff.get('shared-session-notice').hidden,true);
 console.log('Web chat UI: 14 scenarios passed (9 transport/voice regressions, persisted preferences/conflicts, direction preview/immutable retry, isolated context/draft preservation, explicit memory consent/deletion, session ownership/handoff).');

})().catch(e=>{console.error(e);process.exitCode=1;});
