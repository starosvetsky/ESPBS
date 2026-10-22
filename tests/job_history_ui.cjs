// Dependency-free behavior test; not a browser/layout test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function element() {
  return {children: [], append(child) { this.children.push(child); },
    set innerHTML(value) { this.children = []; this.html = value; }};
}
const nodes = {'#jobs': element(), '#connection': element()};
const pending = [];
const context = vm.createContext({
  document: {querySelector: id => nodes[id], createElement: element},
  fetch: url => new Promise(resolve => pending.push({url, resolve})),
  sourceLabel: value => value, escapeHtml: value => value,
});
const source = fs.readFileSync(require('node:path').join(__dirname, '../espbs/web/app.js'), 'utf8');
vm.runInContext(source.slice(0, source.indexOf('async function select(')), context);
const response = (ids, more, cursor) => ({ok: true, json: async () => ({
  jobs: ids.map(id => ({id, source: 'fixture', state: 'COMPLETED', completed: 1, target: 1})),
  has_more: more, next_cursor: cursor,
})});
const settle = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  let work = vm.runInContext('loadJobs()', context);
  assert.equal(pending[0].url, 'api/jobs?limit=25&after=');
  pending.shift().resolve(response(['new'], true, 'new'));
  await work;
  let nav = nodes['#jobs'].children.at(-1);
  assert.equal(nav.children[0].disabled, true);
  nav.children[1].onclick();
  assert.equal(pending[0].url, 'api/jobs?limit=25&after=new');
  pending.shift().resolve(response(['old'], false, null));
  await settle();
  nav = nodes['#jobs'].children.at(-1);
  assert.equal(nav.children[1].disabled, true);
  nav.children[2].onclick();
  assert.equal(pending[0].url, 'api/jobs?limit=25&after=');
  pending.shift().resolve(response(['new'], true, 'new'));
  await settle();
  const older = vm.runInContext('loadJobs()', context);
  const newer = vm.runInContext('loadJobs()', context);
  const oldRequest = pending.shift();
  pending.shift().resolve(response(['latest'], false, null));
  await newer;
  oldRequest.resolve(response(['stale'], false, null));
  await older;
  assert.match(nodes['#jobs'].children[0].html, /latest/);
  assert.doesNotMatch(nodes['#jobs'].children[0].html, /stale/);
  console.log('History UI: navigation and stale-response guard passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
