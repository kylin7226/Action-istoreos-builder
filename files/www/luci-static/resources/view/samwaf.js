'use strict';
'require view';
'require fs';
'require ui';
'require poll';

var CTL = '/usr/libexec/samwafctl';

function ctl(args) {
	return fs.exec(CTL, args).then(function (res) {
		var data;
		try { data = JSON.parse((res.stdout || '').trim()); }
		catch (e) { throw new Error(_('助手没有返回有效 JSON：') + (res.stderr || '')); }
		if (res.code !== 0 || !data.ok)
			throw new Error(data.error || res.stderr || _('操作失败'));
		return data;
	});
}

function consoleURL(port) {
	var url = new URL(location.href);
	url.protocol = 'http:';
	url.port = String(port || 26666);
	url.pathname = '/';
	url.search = '';
	url.hash = '';
	return url.href;
}

function el(id) { return document.getElementById(id); }
function notify(error) { ui.addNotification(null, E('p', String(error.message || error)), 'error'); }

return view.extend({
	load: function () {
		return Promise.all([ctl(['status']), ctl(['upgrade_status'])]);
	},

	setBusy: function (busy) {
		this._busy = busy;
		document.querySelectorAll('.sw-write').forEach(function (button) {
			button.disabled = busy || !L.hasViewPermission();
		});
	},

	paintStatus: function (st) {
		this._port = st.port;
		el('sw-status').textContent = st.running ? _('运行中') : _('已停止');
		el('sw-pid').textContent = String(st.pid || '-');
		el('sw-ver').textContent = st.version;
		el('sw-port').textContent = String(st.port);
		el('sw-enabled').textContent = st.enabled ? _('已开启') : _('未开启');
		var url = consoleURL(st.port);
		el('sw-open').href = url;
		var frame = el('sw-frame');
		if (frame.getAttribute('src') && frame.src !== url) frame.src = url;
		if (document.activeElement !== el('sw-port-input')) el('sw-port-input').value = st.port;
	},

	handleRefresh: function () {
		return ctl(['status']).then(this.paintStatus.bind(this)).catch(notify);
	},

	handleControl: function (action) {
		if (this._busy || !L.hasViewPermission()) return;
		return ctl([action]).then(this.paintStatus.bind(this)).catch(notify);
	},

	handleSetPort: function () {
		if (this._busy || !L.hasViewPermission()) return;
		var value = String(el('sw-port-input').value).trim();
		if (!/^[0-9]{1,5}$/.test(value) || +value < 1 || +value > 65535) {
			notify(_('端口必须是 1–65535 的整数'));
			return;
		}
		return ctl(['set_port', String(Number(value))]).then(function (result) {
			ui.addNotification(null, E('p', _('端口已保存：') + result.port));
			return this.handleRefresh();
		}.bind(this)).catch(notify);
	},

	handlePasswordHelp: function () {
		ui.showModal(_('账号与密码管理'), [
			E('p', _('修改用户名和密码请打开 SamWaf 控制台，在账号管理中操作。')),
			E('p', _('忘记密码时，请通过 SSH 或网页终端执行下列命令，并按提示选择要恢复的账号；不会在此页面自动执行交互式重置。')),
			E('pre', '/etc/init.d/samwaf stop\ncd /opt/samwaf\n/usr/bin/samwaf resetpwd'),
			E('p', _('完成后，如果服务原先在运行，再执行 /etc/init.d/samwaf start。')),
			E('button', { 'class': 'btn', 'click': ui.hideModal }, _('关闭'))
		]);
	},

	stopUpgradePoll: function () {
		if (this._upgradePoll) poll.remove(this._upgradePoll);
		this._upgradePoll = null;
	},

	pollUpgrade: function () {
		if (this._upgradePoll) return;
		this._pollErrors = 0;
		this._upgradePoll = function () {
			if (!el('sw-up-log')) { this.stopUpgradePoll(); return; }
			return ctl(['upgrade_status']).then(function (state) {
				this._pollErrors = 0;
				el('sw-up-log').textContent = state.log || _('等待后台任务…');
				if (!state.running) {
					this.stopUpgradePoll();
					this.setBusy(false);
					ui.addNotification(null, E('p', state.done === true ? _('升级完成') : _('升级未完成，请检查日志')));
					return this.handleRefresh();
				}
			}.bind(this)).catch(function (error) {
				if (++this._pollErrors >= 3) {
					this.stopUpgradePoll();
					this.setBusy(false);
					notify(_('升级状态查询失败，请刷新页面确认后台任务状态。') + ' ' + error.message);
				}
			}.bind(this));
		}.bind(this);
		poll.add(this._upgradePoll, 3);
	},

	handleUpgrade: function () {
		if (this._busy || !L.hasViewPermission()) return;
		var version = String(el('sw-ver-input').value).trim();
		if (version.length > 64 || !/^v?[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.]+)?$/.test(version)) {
			notify(_('请输入有效版本号，例如 v1.3.24'));
			return;
		}
		version = 'v' + version.replace(/^v/, '');
		ui.showModal(_('确认升级'), [
			E('p', _('将下载、备份并替换 SamWaf；期间服务会短暂停止。目标版本：') + version),
			E('button', { 'class': 'btn', 'click': ui.hideModal }, _('取消')),
			E('button', { 'class': 'btn cbi-button-apply', 'click': function () {
				ui.hideModal();
				this.setBusy(true);
				return ctl(['upgrade', version]).then(function () {
					el('sw-up-log').textContent = _('等待后台任务…');
					this.pollUpgrade();
				}.bind(this)).catch(function (error) { this.setBusy(false); notify(error); }.bind(this));
			}.bind(this) }, _('确认升级'))
		]);
	},

	handleToggleFrame: function () {
		var wrap = el('sw-frame-wrap');
		var show = wrap.style.display === 'none';
		wrap.style.display = show ? '' : 'none';
		el('sw-frame-btn').textContent = show ? _('隐藏内嵌控制台') : _('内嵌显示控制台');
		if (show && !el('sw-frame').getAttribute('src')) el('sw-frame').src = consoleURL(this._port);
	},

	render: function (data) {
		this.stopUpgradePoll();
		var st = data[0], upgrade = data[1];
		this._port = st.port;
		this._busy = upgrade.running;
		var self = this;
		function button(text, method, arg) {
			return E('button', { 'class': 'cbi-button sw-write', 'disabled': self._busy || !L.hasViewPermission(),
				'click': ui.createHandlerFn(self, method, arg) }, _(text));
		}
		function row(label, id, value) {
			return E('tr', [E('td', _(label)), E('td', { 'id': id }, String(value))]);
		}
		if (upgrade.running) this.pollUpgrade();
		return E('div', { 'class': 'cbi-map' }, [
			E('h2', _('SamWaf Web 应用防火墙')),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', _('运行状态')),
				E('table', { 'class': 'table' }, [
					row('状态', 'sw-status', st.running ? _('运行中') : _('已停止')),
					row('进程 PID', 'sw-pid', st.pid || '-'), row('版本', 'sw-ver', st.version),
					row('管理端口', 'sw-port', st.port), row('开机自启', 'sw-enabled', st.enabled ? _('已开启') : _('未开启'))
				]),
				button('启动', 'handleControl', 'start'), button('停止', 'handleControl', 'stop'),
				button('重启', 'handleControl', 'restart'), button('开启自启', 'handleControl', 'enable'),
				button('关闭自启', 'handleControl', 'disable'),
				E('button', { 'class': 'cbi-button', 'click': ui.createHandlerFn(this, 'handleRefresh') }, _('刷新'))
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', _('控制台与账号')),
				E('a', { 'id': 'sw-open', 'href': consoleURL(st.port), 'target': '_blank', 'rel': 'noopener', 'class': 'cbi-button' }, _('新标签页打开控制台')),
				E('button', { 'id': 'sw-frame-btn', 'class': 'cbi-button', 'click': ui.createHandlerFn(this, 'handleToggleFrame') }, _('内嵌显示控制台')),
				E('button', { 'class': 'cbi-button', 'click': ui.createHandlerFn(this, 'handlePasswordHelp') }, _('账号与密码管理')),
				E('p', _('初始密码见 /opt/samwaf/data/initial_password.txt；用户名可能已被修改。HTTPS 混合内容或防嵌入策略可能阻止 iframe，请改用新标签页。')),
				E('div', { 'id': 'sw-frame-wrap', 'style': 'display:none' }, [E('iframe', { 'id': 'sw-frame', 'title': 'SamWaf', 'style': 'width:100%;height:70vh;border:1px solid #ccc' })])
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', _('管理端口')),
				E('input', { 'id': 'sw-port-input', 'aria-label': _('管理端口'), 'type': 'number', 'min': 1, 'max': 65535, 'value': st.port }),
				button('保存端口', 'handleSetPort')
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', _('升级')),
				E('p', _('仅支持官方静态 ARM64 release。升级失败会尝试恢复二进制及 conf/data/ssl；请仍保留独立备份。原先停止的服务在验证后保持停止。')),
				E('input', { 'id': 'sw-ver-input', 'aria-label': _('目标版本'), 'value': st.version === 'unknown' ? 'v1.3.24' : st.version }),
				button('开始升级', 'handleUpgrade'),
				E('pre', { 'id': 'sw-up-log', 'style': 'white-space:pre-wrap;max-height:20em;overflow:auto' }, upgrade.log || _('暂无升级日志'))
			])
		]);
	},

	handleSave: null,
	handleSaveApply: null,
	handleReset: null
});
