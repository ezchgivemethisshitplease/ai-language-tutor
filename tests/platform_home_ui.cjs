/* Read-only overview, safe context links and recoverable network failures. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname,'../apps/index.html'),'utf8');
const source = fs.readFileSync(path.join(__dirname,'../apps/platform.js'),'utf8');
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.handlers={};this.hidden=false;this._text='';this.className='';}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  set innerHTML(_){throw new Error('Unsafe HTML insertion');}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this._text='';this.children=children;}
  addEventListener(type,handler){this.handlers[type]=handler;}
  click(){return this.handlers.click?.();}
  remove(){}
}
async function runtime(status,{offline=false,backupError=false,page='home'}={}){
  const markup=page==='home'?html:fs.readFileSync(path.join(__dirname,'../apps/dashboard.html'),'utf8');
  const code=page==='home'?source:fs.readFileSync(path.join(__dirname,'../apps/progress.js'),'utf8');
  const elements=new Map([...markup.matchAll(/<([\w-]+)\b[^>]*\bid="([^"]+)"[^>]*>/g)].map(match=>[match[2],new Element(match[1])]));
  const get=id=>elements.get(id); const requests=[]; let fail=offline;
  const context=vm.createContext({document:{getElementById:get,createElement:tag=>new Element(tag),body:new Element('body')},Tutor:{ready:Promise.resolve(),request:async(route,options={})=>{requests.push({route,options});if(fail||route.endsWith('/backup')&&backupError)throw new Error('offline');return{json:async()=>status,blob:async()=>({})};}},window:{},URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL(){}},setTimeout(){},Intl,Date,Number,Math,Set,Array,Object,String,encodeURIComponent});
  vm.runInContext(code,context);await (page==='home'?context.window.TutorPlatformReady:context.window.TutorProgressReady);
  return{get,requests,online:()=>{fail=false;}};
}
(async()=>{
  const empty=await runtime({initialized:false,auth:{status:'unauthenticated'}});
  assert.equal(empty.get('next-action').href,'chat.html?setup=1');
  assert.equal(empty.get('attempt-count').textContent,'0');
  assert.equal(empty.get('level-status').textContent,'Ещё знакомимся');
  assert.equal(empty.requests.length,1);assert(empty.requests.every(call=>!call.options.method));

  const novice=await runtime({initialized:true,auth:{status:'chatgpt'},profile:{daily_minutes:15},platform_summary:{observation_count:7,completed_sessions:2,due_count:4,working_level:'A1',proficiency_status:'unassessed'}});
  assert.equal(novice.get('next-action').href,'chat.html?new=1&mode=diagnostic');
  assert.equal(novice.get('attempt-count').textContent,'7');assert.equal(novice.get('due-count').textContent,'4');
  assert(!novice.get('level-status').textContent.includes('A1'));
  assert.equal(novice.get('direction-list').children.length,4);
  assert(novice.get('direction-list').children[1].href.endsWith('direction=work'));

  const legacyPlan=await runtime({initialized:true,session:{id:'legacy-plan',status:'active',plan:{steps:[{id:'a',type:'practice'}]}},platform_summary:{proficiency_status:'unassessed',active_session_owner:null,next_action:{kind:'continue',conversation_id:'prior-chat'}}});
  assert.equal(legacyPlan.get('next-action').href,'chat.html?conversation=prior-chat');
  assert.match(legacyPlan.get('next-title').textContent,/сохранённое занятие/);

  const continuingStatus={initialized:true,auth:{status:'chatgpt'},platform_summary:{active_session_owner:{conversation_id:'safe-id',title:'<script>literal title</script>'}},conversations:[{id:'bad&parameter=other',title:'<img onerror=alert(1)>',context:{goal:'A real goal'}}],session:{plan:{steps:[{id:'a',type:'practice'}]},completed_steps:['a']}};
  continuingStatus.conversations.push({id:'literal-safe-id',title:'<img onerror=alert(1)>',context:{goal:'A real goal'}});
  const continuing=await runtime(continuingStatus);
  assert.equal(continuing.get('next-action').href,'chat.html?conversation=safe-id');
  assert.match(continuing.get('next-title').textContent,/<script>literal title<\/script>/);
  assert.equal(continuing.get('recent-conversations').children[0].href,'chat.html?conversation=literal-safe-id');
  assert.match(continuing.get('recent-conversations').textContent,/<img onerror=alert\(1\)>/);
  assert.equal(continuing.get('daily-route').children[0].className,'done');
  assert.equal(continuing.get('recent-conversations').children.length,1);
  continuingStatus.session=null;await continuing.get('reload-page').click();
  assert.equal(continuing.get('daily-route').children.length,0);
  assert.equal(continuing.get('daily-route').hidden,true);

  const professional=await runtime({initialized:true,personalization:{account_preferences:{dialect:'uk',register:'professional',explanation_style:'detailed',grammar_terminology:'standard',notes:'<b>My exact preference</b>'}},platform_summary:{working_level:'B1',proficiency_status:'human_reviewed_curriculum_progression'}});
  assert.equal(professional.get('dialect-label').textContent,'British English');
  assert.equal(professional.get('approach-description').textContent,'<b>My exact preference</b>');
  assert.match(professional.get('preference-tags').textContent,/С подробностями/);

  const offline=await runtime({initialized:false},{offline:true});
  assert.equal(offline.get('page-error').hidden,false);offline.online();await offline.get('reload-page').click();
  assert.equal(offline.get('page-error').hidden,true);

  const backup=await runtime({initialized:true},{backupError:true});await backup.get('home-backup').click();
  assert.equal(backup.get('home-backup').disabled,false);assert.equal(backup.get('page-error').hidden,false);
  const progress=await runtime({platform_summary:{observation_count:12,completed_sessions:1,due_count:3,working_level:'A1',proficiency_status:'unassessed',domains:{reading:{eligible_attempts:2}},recent_activity:[{date:'2026-10-17',attempts:12}],pending_review_count:2}},{page:'progress'});
  assert.equal(progress.get('progress-attempts').textContent,'12');
  assert.equal(progress.get('progress-level').textContent,'Уровень ещё не оценён');
  assert.equal(progress.get('skill-list').children.length,4);
  assert.match(progress.get('skill-list').children[0].textContent,/2/);
  assert.match(progress.get('pending-review-copy').textContent,/2 ответов/);
  const progressOffline=await runtime({platform_summary:{}},{page:'progress',offline:true});
  assert.equal(progressOffline.get('page-error').hidden,false);progressOffline.online();await progressOffline.get('reload-page').click();
  assert.equal(progressOffline.get('page-error').hidden,true);
  for (const page of ['home','progress']) {
    const unavailable=await runtime({auth:{status:'unavailable',error:'Synthetic CLI failure'}},{page});
    assert.equal(unavailable.get('service-status').textContent,'Преподаватель недоступен');
    assert.equal(unavailable.get('page-error').hidden,false);
  }
  console.log('Platform overview: 12 scenarios passed (read-only setup, honest evidence, scoped resume, unbound legacy plan, stale plan cleared, literal preferences, load recovery, backup failure, separate skill evidence, progress retry, teacher outage on both pages).');
})().catch(error=>{console.error(error);process.exitCode=1;});
