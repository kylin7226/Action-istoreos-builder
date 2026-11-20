const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const nodes = new Map();
let writable = true, responseCode = 0, frameLoads = 0;
let state = { ok: true, running: true, pid: 123, enabled: true, port: 26666, version: 'v1.3.24' };
let upgrade = { ok: true, running: false, done: null, log: '' };
const calls = [], notifications = [], queue = new Set();
let modal;
function E(tag, attrs, children) {
  if (!attrs || typeof attrs !== 'object' || Array.isArray(attrs)) { children = attrs; attrs = {}; }
  const element = { tag, attrs, children, style: { display: attrs.style?.includes('display:none') ? 'none' : '' },
    value: attrs.value, textContent: typeof children === 'string' ? children : '', disabled: attrs.disabled,
    getAttribute(name) { return this.attrs[name] ?? null; } };
  Object.defineProperty(element, 'src', {
    get() { return this.attrs.src || ''; },
    set(value) { this.attrs.src = value; frameLoads++; }
  });
  if (attrs.id) nodes.set(attrs.id, element);
  return element;
}
const context = {
  URL, Promise, console, location: { href: 'http://[::1]/cgi-bin/luci/admin/services/samwaf' },
  document: { activeElement: null, getElementById: id => nodes.get(id),
    querySelectorAll: () => [] },
  L: { hasViewPermission: () => writable }, E, _: text => text,
  view: { extend: value => value }, poll: { add: fn => queue.add(fn), remove: fn => queue.delete(fn) },
  ui: { addNotification: (...args) => notifications.push(args), showModal: (title, body) => { modal = body; },
    hideModal() {}, createHandlerFn: (self, method, arg) => () => self[method](arg) },
  fs: { exec: async (command, args) => {
    calls.push(args);
    let data = state;
    if (args[0] === 'upgrade_status') data = upgrade;
    if (args[0] === 'set_port') { state = { ...state, port: Number(args[1]) }; data = { ok: true, port: state.port }; }
    if (args[0] === 'upgrade') data = { ok: true };
    return { code: responseCode, stdout: JSON.stringify(data), stderr: responseCode ? 'command failed' : '' };
  } }
};
const source = fs.readFileSync(path.join(__dirname, '../files/www/luci-static/resources/view/samwaf.js'), 'utf8');
const page = vm.runInNewContext('(function () {\n' + source + '\n})()', context);

(async () => {
  const data = await page.load();
  page.render(data);
  assert.equal(nodes.get('sw-frame').getAttribute('src'), null, 'iframe must be lazy');
  page.paintStatus(state);
  assert.equal(frameLoads, 0);
  page.handleToggleFrame();
  assert.equal(frameLoads, 1);
  assert.equal(nodes.get('sw-frame').src, 'http://[::1]:26666/');
  page.paintStatus(state);
  assert.equal(frameLoads, 1, 'unchanged status must not reload iframe');
  nodes.get('sw-port-input').value = '08080';
  await page.handleSetPort();
  assert(calls.some(args => args[0] === 'set_port' && args[1] === '8080'));
  assert.equal(frameLoads, 2);
  const callCount = calls.length;
  nodes.get('sw-port-input').value = '999999999999999';
  await page.handleSetPort();
  assert.equal(calls.length, callCount);

  const unrelated = () => {};
  queue.add(unrelated);
  upgrade = { ok: true, running: true, done: null, log: 'downloading' };
  page.pollUpgrade();
  const first = page._upgradePoll;
  page.pollUpgrade();
  assert.equal(queue.size, 2, 'one upgrade callback only');
  await first();
  assert.equal(nodes.get('sw-up-log').textContent, 'downloading');
  upgrade = { ok: true, running: false, done: true, log: 'done' };
  await first();
  assert.equal(queue.size, 1);
  assert(queue.has(unrelated), 'other LuCI poll callbacks must survive');
  page.pollUpgrade();
  assert.equal(queue.size, 2, 'a second upgrade can poll');
  responseCode = 1;
  await page._upgradePoll(); await page._upgradePoll(); await page._upgradePoll();
  assert.equal(page._upgradePoll, null, 'failed polling must not loop forever');
  assert(queue.has(unrelated));
  responseCode = 0;

  writable = false;
  const before = calls.length;
  await page.handleControl('stop');
  await page.handleSetPort();
  page.handleUpgrade();
  assert.equal(calls.length, before, 'read-only UI cannot perform writes');
  writable = true;
  responseCode = 1;
  await page.handleControl('start');
  assert(notifications.some(args => String(args[1].textContent).includes('command failed')));
  responseCode = 0;
  const passwordCalls = calls.length;
  page.handlePasswordHelp();
  assert.equal(calls.length, passwordCalls, 'password guide must not reset accounts');
  assert(modal.some(element => String(element.textContent).includes('resetpwd')));
  console.log('LuCI regression checks passed: lazy iframe, IPv6, ports, poll isolation/retry, readonly, RPC failures, password guide');
})().catch(error => { console.error(error); process.exitCode = 1; });
