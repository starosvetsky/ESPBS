// Dependency-free state/navigation regression; browser smoke is separate.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function element(){return {children:[],dataset:{},append(node){this.children.push(node);},
  replaceChildren(...nodes){this.children=nodes;},
  querySelector(selector){return this.children.find(n=>'.'+n.className===selector);}};}
const nodes={};
for(const name of ['stream-controls','prepare','include-files','cleanup','archive-status','archive-meta','resume'])nodes['#'+name]=element();
const requests=[],selected=[];
const context=vm.createContext({stateName:{},$:id=>nodes[id],document:{createElement:element},
  formatBytes:n=>String(n),api:url=>new Promise(resolve=>requests.push({url,resolve})),
  select:id=>selected.push(id),alert:()=>{},post:async()=>({}),loadDetail:()=>{}});
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../espbs/web/streaming.js'),'utf8'),context);
const job={id:'parent',state:'WAITING_PARTS',stream:{occupied:2,window:2,can_prepare:false,
  budget:{versions:51,max_versions:10000,payload_bytes:500,max_payload_bytes:67108864}}};
const render=value=>{context.job=value;vm.runInContext('renderStreaming(job)',context);};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const page=(seq,more=false)=>({parts:[{seq,start_seq:seq-1,end_seq:seq,child_id:'child'+seq,ready:true,record_count:1}],has_more:more,next_cursor:seq});
(async()=>{
  render(job);
  assert.equal(nodes['#resume'].disabled,true);
  const box=nodes['#stream-controls'],list=box.querySelector('.stream-list');
  requests.shift().resolve(page(1,true));await settle();
  list.children[0].onclick();assert.deepEqual(selected,['child1']);
  list.children.at(-1).onclick();assert.match(requests[0].url,/after=1$/);
  requests.shift().resolve(page(2));await settle();
  assert.equal(list.children.at(-1).disabled,true);
  list.children.at(-2).onclick();assert.match(requests[0].url,/after=0$/);
  const stale=requests.shift();
  render({...job,state:'WAITING_PARTS',stream:{...job.stream,occupied:1}});
  assert.equal(nodes['#resume'].disabled,false);
  requests.shift().resolve(page(3));await settle();
  stale.resolve(page(99));await settle();
  assert.match(list.children[0].textContent,/Часть 3:/);
  render({...job,state:'PAUSED_JOURNAL',stream:{...job.stream,occupied:0}});
  assert.equal(nodes['#resume'].disabled,true);
  requests.shift().resolve(page(4));await settle();
  render({...job,state:'RUNNING',stream:{...job.stream,occupied:0,can_prepare:true}});
  assert.equal(box.querySelector('.stream-summary').children.at(-1).disabled,true);
  const pending=requests.shift();render({id:'ordinary'});
  pending.resolve(page(5));await settle();
  assert.equal(box.hidden,true);assert.equal(box.children.length,0);
  console.log('Streaming UI: pause controls, pagination, stale responses and switching passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
