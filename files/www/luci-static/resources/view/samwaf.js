'use strict';
'require view';
'require fs';
'require ui';
'require poll';

var CTL = '/usr/libexec/samwafctl';

function ctl(args) {
	return fs.exec(CTL, args).then(function (res) {
		var out = ((res && res.stdout) || '').trim();
		try {
			return JSON.parse(out);
		} catch (e) {
			return { ok: false, error: '助手无有效 JSON 输出', raw: out, stderr: (res && res.stderr) || '', code: (res && res.code) };
		}
	}).catch(function (err) {
		return { ok: false, error: String((err && err.message) || err) };
	});
}

function b64text(b64) {
	if (!b64) return '';
	try { return decodeURIComponent(escape(atob(b64))); }
	catch (e) { try { return atob(b64); } catch (e2) { return ''; } }
}

function consoleURL(port) {
	return 'http://' + location.hostname + ':' + (port || 26666) + '/';
}

function el(id) { return document.getElementById(id); }

return view.extend({
	load: function () {
		return ctl(['status']);
	},

	paintStatus: function (st) {
		if (!st || st.running === undefined) return;
		var run = el('sw-run');
		if (run) {
			run.textContent = st.running ? _('运行中') : _('已停止');
			run.className = 'sw-badge ' + (st.running ? 'sw-on' : 'sw-off');
		}
		if (el('sw-pid'))  el('sw-pid').textContent  = st.pid || '-';
		if (el('sw-ver'))  el('sw-ver').textContent  = st.version || 'unknown';
		if (el('sw-port')) el('sw-port').textContent = st.port || '-';
		if (el('sw-en'))   el('sw-en').textContent   = st.enabled ? _('已开启') : _('未开启');

		var url = consoleURL(st.port);
		if (el('sw-open'))  el('sw-open').href = url;
		if (el('sw-frame')) el('sw-frame').src = url;
		var pi = el('sw-port-input');
		if (pi && document.activeElement !== pi) pi.value = st.port || 26666;
	},

	handleControl: function (action) {
		var self = this;
		return ctl([action]).then(function (st) {
			self.paintStatus(st);
			if (st && st.error) ui.addNotification(null, E('p', st.error));
		});
	},

	handleRefresh: function () {
		var self = this;
		return ctl(['status']).then(function (st) { self.paintStatus(st); });
	},

	handleSetPort: function () {
		var self = this;
		var input = el('sw-port-input');
		var v = input ? String(input.value || '').trim() : '';
		if (!/^[0-9]+$/.test(v) || +v < 1 || +v > 65535) {
			ui.addNotification(null, E('p', _('端口需为 1-65535 的数字')));
			return;
		}
		return ctl(['set_port', v]).then(function (r) {
			if (r && r.ok)
				ui.addNotification(null, E('p', _('端口已保存为') + ' ' + r.port + (r.restarted ? _('，并已重启生效') : _('，将在下次启动时生效'))));
			else
				ui.addNotification(null, E('p', _('保存失败：') + ((r && r.error) || _('未知错误'))));
			return ctl(['status']).then(function (st) { self.paintStatus(st); });
		});
	},

	handleResetPwd: function () {
		ui.showModal(_('重置管理员密码'), [
			E('p', { 'class': 'spinning' }, _('正在重置…（会短暂停止再启动服务）'))
		]);
		return ctl(['resetpwd']).then(function (r) {
			ui.hideModal();
			var close = E('div', { 'class': 'right' },
				E('button', { 'class': 'btn', 'click': ui.hideModal }, _('关闭')));
			if (r && r.ok) {
				ui.showModal(_('新密码'), [
					E('p', _('管理员 admin 的新密码（随机生成，请立即保存并登录修改）：')),
					E('p', { 'style': 'font-size:1.4em;font-weight:bold;user-select:all' }, r.password),
					close
				]);
			} else {
				ui.showModal(_('重置失败'), [
					E('p', (r && r.error) || _('未知错误')),
					(r && r.raw) ? E('pre', { 'style': 'white-space:pre-wrap;font-size:.9em' }, r.raw) : '',
					close
				]);
			}
		});
	},

	pollUpgrade: function () {
		var self = this;
		var box = el('sw-up-log');
		poll.add(function () {
			return ctl(['upgrade_status']).then(function (s) {
				if (box) box.textContent = b64text(s && s.log_b64) || _('（暂无输出）');
				if (s && !s.running && s.done !== null && s.done !== undefined) {
					poll.stop();
					ui.addNotification(null, E('p', s.done ? _('✅ 升级完成，服务已重启') : _('❌ 升级失败，详见日志')));
					return ctl(['status']).then(function (st) { self.paintStatus(st); });
				}
			});
		}, 3);
	},

	handleUpgrade: function () {
		var self = this;
		var input = el('sw-ver-input');
		var v = input ? String(input.value || '').trim() : '';
		if (!v) { ui.addNotification(null, E('p', _('请先填写目标版本号，如 v1.3.24'))); return; }
		return ctl(['upgrade', v]).then(function (r) {
			if (!r || !r.ok) {
				ui.addNotification(null, E('p', _('升级启动失败：') + ((r && r.error) || _('未知错误'))));
				return;
			}
			ui.addNotification(null, E('p', _('已开始后台升级到') + ' ' + v + _('，下方显示进度…')));
			self.pollUpgrade();
		});
	},

	handleToggleFrame: function () {
		var wrap = el('sw-frame-wrap');
		var btn = el('sw-frame-btn');
		var frame = el('sw-frame');
		if (!wrap) return;
		var show = wrap.style.display === 'none';
		wrap.style.display = show ? '' : 'none';
		if (btn) btn.textContent = show ? _('隐藏内嵌控制台') : _('内嵌显示控制台');
		if (show && frame && !frame.src) frame.src = consoleURL(this._port);
	},

	render: function (data) {
		var self = this;
		var st = data || {};
		this._port = st.port || 26666;
		var url = consoleURL(st.port);

		var css = E('style', {},
			'.sw-badge{padding:.1em .6em;border-radius:1em;color:#fff;font-weight:bold}' +
			'.sw-on{background:#5cb85c}.sw-off{background:#999}' +
			'.sw-hint{color:#888;font-size:.9em;margin:.3em 0}' +
			'.sw-row{margin:.6em 0}.sw-row input{margin-right:.5em}' +
			'#sw-up-log{white-space:pre-wrap;background:#111;color:#9f9;padding:.6em;border-radius:4px;max-height:18em;overflow:auto;font-size:.85em}' +
			'#sw-frame{width:100%;height:78vh;border:1px solid #ccc}');

		var statusSec = E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, _('运行状态')),
			E('table', { 'class': 'table' }, [
				E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td', 'style': 'width:12em' }, _('状态')),
					E('td', { 'class': 'td' }, E('span', { 'id': 'sw-run', 'class': 'sw-badge ' + (st.running ? 'sw-on' : 'sw-off') }, st.running ? _('运行中') : _('已停止'))) ]),
				E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td' }, _('进程 PID')), E('td', { 'class': 'td' }, E('span', { 'id': 'sw-pid' }, String(st.pid || '-'))) ]),
				E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td' }, _('当前版本')), E('td', { 'class': 'td' }, E('span', { 'id': 'sw-ver' }, st.version || 'unknown')) ]),
				E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td' }, _('监听端口')), E('td', { 'class': 'td' }, E('span', { 'id': 'sw-port' }, String(st.port || '-'))) ]),
				E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td' }, _('开机自启')), E('td', { 'class': 'td' }, E('span', { 'id': 'sw-en' }, st.enabled ? _('已开启') : _('未开启'))) ])
			]),
			E('div', { 'class': 'sw-row' }, [
				E('button', { 'class': 'cbi-button cbi-button-positive', 'click': ui.createHandlerFn(this, 'handleControl', 'start') }, _('启动')),
				E('button', { 'class': 'cbi-button cbi-button-negative', 'style': 'margin-left:.4em', 'click': ui.createHandlerFn(this, 'handleControl', 'stop') }, _('停止')),
				E('button', { 'class': 'cbi-button cbi-button-action', 'style': 'margin-left:.4em', 'click': ui.createHandlerFn(this, 'handleControl', 'restart') }, _('重启')),
				E('button', { 'class': 'cbi-button', 'style': 'margin-left:.4em', 'click': ui.createHandlerFn(this, 'handleControl', 'enable') }, _('开启自启')),
				E('button', { 'class': 'cbi-button', 'style': 'margin-left:.4em', 'click': ui.createHandlerFn(this, 'handleControl', 'disable') }, _('关闭自启')),
				E('button', { 'class': 'cbi-button', 'style': 'margin-left:.4em', 'click': ui.createHandlerFn(this, 'handleRefresh') }, _('刷新'))
			])
		]);

		var portSec = E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, _('管理端口')),
			E('p', { 'class': 'sw-hint' }, _('修改后写入 UCI 并同步到 conf/config.yml 的 local_port；若服务在运行会自动重启生效。')),
			E('div', { 'class': 'sw-row' }, [
				E('input', { 'id': 'sw-port-input', 'type': 'number', 'min': '1', 'max': '65535', 'value': String(st.port || 26666), 'style': 'width:8em' }),
				E('button', { 'class': 'cbi-button cbi-button-save', 'click': ui.createHandlerFn(this, 'handleSetPort') }, _('保存端口'))
			])
		]);

		var pwdSec = E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, _('管理员密码')),
			E('p', { 'class': 'sw-hint' },
				_('账号固定为 admin。SamWaf 的命令行 resetpwd 只能生成随机密码（无法自定义），改自定义密码/改名请登录后在其控制台内进行。')),
			E('p', { 'class': 'sw-hint' },
				_('首次启动的初始随机密码保存在设备：') + ' /opt/samwaf/data/initial_password.txt'),
			E('div', { 'class': 'sw-row' }, [
				E('button', { 'class': 'cbi-button cbi-button-action', 'click': ui.createHandlerFn(this, 'handleResetPwd') }, _('重置为新的随机密码'))
			])
		]);

		var upSec = E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, _('升级')),
			E('p', { 'class': 'sw-hint' },
				_('从官方 GitHub release 下载对应版本的 arm64 静态包，校验 sha256 后替换二进制并重启（约 86MB，需设备能访问 GitHub）。版本号示例：v1.3.24。')),
			E('div', { 'class': 'sw-row' }, [
				E('input', { 'id': 'sw-ver-input', 'type': 'text', 'value': st.version && st.version !== 'unknown' ? st.version : 'v1.3.24', 'style': 'width:12em', 'placeholder': 'v1.3.24' }),
				E('button', { 'class': 'cbi-button cbi-button-apply', 'click': ui.createHandlerFn(this, 'handleUpgrade') }, _('开始升级'))
			]),
			E('pre', { 'id': 'sw-up-log' }, _('（升级日志）'))
		]);

		var consoleSec = E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, _('控制台')),
			E('div', { 'class': 'sw-row' }, [
				E('a', { 'id': 'sw-open', 'href': url, 'target': '_blank', 'rel': 'noopener', 'class': 'cbi-button cbi-button-link' }, _('新标签页打开控制台')),
				E('button', { 'id': 'sw-frame-btn', 'class': 'cbi-button', 'style': 'margin-left:.4em', 'click': ui.createHandlerFn(this, 'handleToggleFrame') }, _('内嵌显示控制台'))
			]),
			E('p', { 'class': 'sw-hint' },
				_('内嵌可能失败：SamWaf 后台可能设置了 X-Frame-Options/CSP 防点击劫持，或 LuCI 走 HTTPS 时的混合内容拦截。打不开就用「新标签页打开」。')),
			E('div', { 'id': 'sw-frame-wrap', 'style': 'display:none' }, [
				E('iframe', { 'id': 'sw-frame', 'src': url })
			])
		]);

		return E('div', { 'class': 'cbi-map' }, [
			css,
			E('h2', {}, _('SamWaf Web 应用防火墙')),
			statusSec, consoleSec, portSec, pwdSec, upSec
		]);
	}
});
