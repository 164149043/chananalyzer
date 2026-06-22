(function () {
  'use strict';

  var API_BASE = window.location.origin + '/api';
  var TOKEN_KEY = 'chanalyzer_token';

  // 积分弹窗当前目标与模式
  var creditTarget = null;           // {id, username, credits}
  var creditMode = 'recharge';       // 'recharge' | 'deduct'

  // ============ 工具 ============

  function getToken() { return localStorage.getItem(TOKEN_KEY); }

  function authHeaders() {
    var h = { 'Content-Type': 'application/json' };
    var t = getToken();
    if (t) h['Authorization'] = 'Bearer ' + t;
    return h;
  }

  // XSS 防护：所有自由文本（reason / admin_username）插入前必须转义
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // 统一 API 调用：401 跳登录、403 跳主站、非 ok 抛 detail
  function api(path, options) {
    options = options || {};
    return fetch(API_BASE + path, {
      method: options.method || 'GET',
      headers: authHeaders(),
      body: options.body ? JSON.stringify(options.body) : undefined,
    }).then(function (resp) {
      if (resp.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem('chanalyzer_user_id');
        window.location.href = '/?expired=1';
        throw new Error('未登录');
      }
      if (resp.status === 403) {
        alert('无权访问管理后台（仅管理员可进入）');
        window.location.href = '/app';
        throw new Error('无权限');
      }
      return resp.json().then(function (data) {
        if (!resp.ok) {
          throw new Error((data && data.detail) || ('请求失败 (' + resp.status + ')'));
        }
        return data;
      });
    });
  }

  function fmtTime(s) {
    if (!s) return '-';
    return s.replace('T', ' ').slice(0, 16); // YYYY-MM-DD HH:MM
  }

  function showError(id, msg) {
    var el = document.getElementById(id);
    el.textContent = msg;
    el.classList.add('show');
  }
  function hideError(id) {
    var el = document.getElementById(id);
    el.textContent = '';
    el.classList.remove('show');
  }

  // ============ 初始化 ============

  function bootstrap() {
    if (!getToken()) { window.location.href = '/'; return; }
    api('/auth/me').then(function (me) {
      if (me.role !== 'admin') {
        alert('非管理员账号，无法进入管理后台');
        window.location.href = '/app';
        return;
      }
      document.getElementById('adminName').textContent = me.username;
      loadUsers();
    }).catch(function () { /* api 已处理跳转 */ });
  }

  // ============ 用户列表 ============

  function loadUsers() {
    var tbody = document.getElementById('usersTbody');
    tbody.innerHTML = '<tr class="empty-row"><td colspan="8" class="loading">加载中...</td></tr>';
    api('/admin/users').then(function (data) {
      document.getElementById('userCount').textContent = '共 ' + data.total + ' 个用户';
      if (!data.users || !data.users.length) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="8">暂无用户</td></tr>';
        return;
      }
      tbody.innerHTML = data.users.map(function (u) {
        var isAdmin = u.role === 'admin';
        var statusBtn = '';
        if (!isAdmin) {
          statusBtn = u.status === 'active'
            ? '<button class="act-btn disable" data-action="toggle" data-id="' + u.id + '" data-status="active">禁用</button>'
            : '<button class="act-btn enable" data-action="toggle" data-id="' + u.id + '" data-status="disabled">启用</button>';
        }
        var dataName = ' data-name="' + escapeHtml(u.username) + '"';
        var dataBal = ' data-bal="' + u.credits + '"';
        return '<tr>' +
          '<td>' + u.id + '</td>' +
          '<td class="username-cell">' + escapeHtml(u.username) + '</td>' +
          '<td><span class="role-tag ' + (isAdmin ? 'role-admin' : 'role-user') + '">' + (isAdmin ? '管理员' : '用户') + '</span></td>' +
          '<td class="credits-cell">' + u.credits + '</td>' +
          '<td><span class="status-tag ' + (u.status === 'active' ? 'status-active' : 'status-disabled') + '">' + (u.status === 'active' ? '启用' : '禁用') + '</span></td>' +
          '<td class="time-cell">' + fmtTime(u.created_at) + '</td>' +
          '<td class="time-cell">' + fmtTime(u.last_login_at) + '</td>' +
          '<td class="actions-cell">' +
            '<button class="act-btn recharge" data-action="recharge" data-id="' + u.id + '"' + dataName + dataBal + '>充值</button>' +
            '<button class="act-btn deduct" data-action="deduct" data-id="' + u.id + '"' + dataName + dataBal + '>扣减</button>' +
            '<button class="act-btn" data-action="tx" data-id="' + u.id + '"' + dataName + '>流水</button>' +
            statusBtn +
          '</td>' +
        '</tr>';
      }).join('');
    }).catch(function (e) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="8">加载失败：' + escapeHtml(e.message) + '</td></tr>';
    });
  }

  // ============ 表格事件委托 ============

  function onTableClick(e) {
    var btn = e.target.closest('button[data-action]');
    if (!btn) return;
    var action = btn.dataset.action;
    var id = parseInt(btn.dataset.id, 10);
    if (action === 'recharge' || action === 'deduct') {
      openCreditModal({
        id: id,
        username: btn.dataset.name,
        credits: parseInt(btn.dataset.bal, 10),
      }, action);
    } else if (action === 'tx') {
      openTxModal(id, btn.dataset.name);
    } else if (action === 'toggle') {
      var cur = btn.dataset.status;           // 当前状态
      var next = cur === 'active' ? 'disabled' : 'active';
      if (!confirm('确定要' + (next === 'disabled' ? '禁用' : '启用') + ' 该用户吗？')) return;
      api('/admin/users/' + id + '/status', { method: 'PUT', body: { status: next } })
        .then(function () { loadUsers(); })
        .catch(function (err) { alert(err.message); });
    }
  }

  // ============ 积分弹窗（充值/扣减） ============

  function openCreditModal(target, mode) {
    creditTarget = target;
    creditMode = mode;
    document.getElementById('creditModalTitle').textContent = mode === 'recharge' ? '充值积分' : '扣减积分';
    document.getElementById('creditModalSub').textContent = '目标用户：' + target.username;
    document.getElementById('creditCurrent').textContent = target.credits;
    document.getElementById('creditAmount').value = '';
    document.getElementById('creditReason').value = '';
    hideError('creditError');
    document.getElementById('creditModal').classList.add('show');
    setTimeout(function () { document.getElementById('creditAmount').focus(); }, 50);
  }

  function closeCreditModal() {
    document.getElementById('creditModal').classList.remove('show');
    creditTarget = null;
  }

  function submitCredit() {
    if (!creditTarget) return;
    var amountRaw = document.getElementById('creditAmount').value;
    var reason = document.getElementById('creditReason').value.trim();
    var amount = parseInt(amountRaw, 10);
    hideError('creditError');
    // 金额必须正整数（防 03、1.5、负数）
    if (!amountRaw || isNaN(amount) || amount <= 0 || String(amount) !== amountRaw.trim()) {
      showError('creditError', '金额必须是正整数');
      return;
    }
    if (!reason) { showError('creditError', '请填写变动原因'); return; }
    if (reason.length > 255) { showError('creditError', '原因不超过 255 字'); return; }

    var delta = creditMode === 'recharge' ? amount : -amount;
    var btn = document.getElementById('creditSubmit');
    btn.disabled = true; btn.textContent = '提交中...';
    api('/admin/users/' + creditTarget.id + '/credits', { method: 'POST', body: { delta: delta, reason: reason } })
      .then(function () { closeCreditModal(); loadUsers(); })
      .catch(function (err) { showError('creditError', err.message); })
      .then(function () { btn.disabled = false; btn.textContent = '确认'; });
  }

  // ============ 流水弹窗 ============

  function openTxModal(userId, username) {
    document.getElementById('txModalSub').textContent = '用户：' + username;
    document.getElementById('txTbody').innerHTML = '<tr><td colspan="5" class="loading">加载中...</td></tr>';
    document.getElementById('txModal').classList.add('show');
    api('/admin/credits/transactions?user_id=' + userId + '&limit=50').then(function (data) {
      var txs = data.transactions || [];
      if (!txs.length) {
        document.getElementById('txTbody').innerHTML = '<tr><td colspan="5" class="tx-empty">暂无流水记录</td></tr>';
        return;
      }
      document.getElementById('txTbody').innerHTML = txs.map(function (t) {
        var cls = t.delta >= 0 ? 'tx-delta-up' : 'tx-delta-down';
        var sign = t.delta >= 0 ? '+' : '';
        return '<tr>' +
          '<td class="time-cell">' + fmtTime(t.created_at) + '</td>' +
          '<td class="' + cls + '">' + sign + t.delta + '</td>' +
          '<td>' + t.balance_after + '</td>' +
          '<td>' + escapeHtml(t.reason) + '</td>' +
          '<td class="time-cell">' + escapeHtml(t.admin_username) + '</td>' +
        '</tr>';
      }).join('');
    }).catch(function (e) {
      document.getElementById('txTbody').innerHTML = '<tr><td colspan="5" class="tx-empty">加载失败：' + escapeHtml(e.message) + '</td></tr>';
    });
  }

  // ============ 事件绑定 ============

  document.getElementById('usersTbody').addEventListener('click', onTableClick);
  document.getElementById('creditCancel').addEventListener('click', closeCreditModal);
  document.getElementById('creditSubmit').addEventListener('click', submitCredit);
  document.getElementById('creditModal').addEventListener('click', function (e) {
    if (e.target === this) closeCreditModal();
  });
  document.getElementById('creditReason').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') submitCredit();
  });
  document.getElementById('txClose').addEventListener('click', function () {
    document.getElementById('txModal').classList.remove('show');
  });
  document.getElementById('txModal').addEventListener('click', function (e) {
    if (e.target === this) this.classList.remove('show');
  });
  document.getElementById('logoutBtn').addEventListener('click', function () {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem('chanalyzer_user_id');
    window.location.href = '/';
  });

  document.addEventListener('DOMContentLoaded', bootstrap);
})();
