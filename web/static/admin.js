(function () {
  'use strict';

  var API_BASE = window.location.origin + '/api';
  var TOKEN_KEY = 'chanalyzer_token';

  // ============ 工具 ============

  function getToken() { return localStorage.getItem(TOKEN_KEY); }

  function authHeaders() {
    var h = { 'Content-Type': 'application/json' };
    var t = getToken();
    if (t) h['Authorization'] = 'Bearer ' + t;
    return h;
  }

  // XSS 防护：所有自由文本插入前必须转义
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
    tbody.innerHTML = '<tr class="empty-row"><td colspan="9" class="loading">加载中...</td></tr>';
    api('/admin/users').then(function (data) {
      var countText = '共 ' + data.total + ' 个用户';
      if (data.pending_count > 0) countText += '，<b style="color:var(--warning,#f59e0b)">' + data.pending_count + ' 个待审核</b>';
      document.getElementById('userCount').innerHTML = countText;
      if (!data.users || !data.users.length) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="9">暂无用户</td></tr>';
        return;
      }
      tbody.innerHTML = data.users.map(function (u) {
        var isAdmin = u.role === 'admin';
        var isPending = u.status === 'pending';
        var dataName = ' data-name="' + escapeHtml(u.username) + '"';
        var statusBtn = '';
        var usageBtn = '';
        var deleteBtn = '';
        if (!isAdmin) {
          if (isPending) {
            // 待审核：通过 / 拒绝
            statusBtn =
              '<button class="act-btn enable" data-action="approve" data-id="' + u.id + '"' + dataName + '>✓ 通过</button>' +
              '<button class="act-btn disable" data-action="reject" data-id="' + u.id + '"' + dataName + '>✗ 拒绝</button>';
          } else {
            statusBtn = u.status === 'active'
              ? '<button class="act-btn disable" data-action="toggle" data-id="' + u.id + '" data-status="active">禁用</button>'
              : '<button class="act-btn enable" data-action="toggle" data-id="' + u.id + '" data-status="disabled">启用</button>';
          }
          usageBtn = '<button class="act-btn member" data-action="reset-usage" data-id="' + u.id + '"' + dataName + '>重置次数</button>';
          deleteBtn = '<button class="act-btn danger" data-action="delete" data-id="' + u.id + '"' + dataName + '>删除</button>';
        }
        // 状态标签
        var statusTag;
        if (isAdmin) {
          statusTag = '<span class="status-tag status-active">管理员</span>';
        } else if (isPending) {
          statusTag = '<span class="status-tag status-pending">⏳ 待审核</span>';
        } else {
          statusTag = '<span class="status-tag ' + (u.status === 'active' ? 'status-active' : 'status-disabled') + '">' + (u.status === 'active' ? '启用' : '禁用') + '</span>';
        }
        // AI 次数单元格
        var usageCell;
        if (isAdmin) {
          usageCell = '<span class="member-perm">不限</span>';
        } else if (u.status !== 'active') {
          usageCell = '<span class="member-perm">-</span>';
        } else if (u.ai_remaining === null || u.ai_remaining === undefined) {
          usageCell = '<span class="member-perm">-</span>';
        } else {
          usageCell = '<span class="' + (u.ai_remaining > 0 ? 'member-active' : 'member-expired') + '">剩 ' + u.ai_remaining + '/' + u.ai_daily_limit + ' 次</span>';
        }
        var rowCls = isPending ? ' style="background:rgba(245,158,11,0.06)"' : '';
        return '<tr' + rowCls + '>' +
          '<td>' + u.id + '</td>' +
          '<td class="username-cell">' + escapeHtml(u.username) + '</td>' +
          '<td class="email-cell"' + (u.email ? ' title="' + escapeHtml(u.email) + '"' : '') + '>' + (u.email ? escapeHtml(u.email) : '<span class="no-email">未绑定</span>') + '</td>' +
          '<td><span class="role-tag ' + (isAdmin ? 'role-admin' : 'role-user') + '">' + (isAdmin ? '管理员' : '用户') + '</span></td>' +
          '<td>' + statusTag + '</td>' +
          '<td class="member-cell">' + usageCell + '</td>' +
          '<td class="time-cell">' + fmtTime(u.created_at) + '</td>' +
          '<td class="time-cell">' + fmtTime(u.last_login_at) + '</td>' +
          '<td class="actions-cell"><div class="actions-inner">' +
            statusBtn +
            usageBtn +
            deleteBtn +
          '</div></td>' +
        '</tr>';
      }).join('');
    }).catch(function (e) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="9">加载失败：' + escapeHtml(e.message) + '</td></tr>';
    });
  }

  // ============ 表格事件委托 ============

  function onTableClick(e) {
    var btn = e.target.closest('button[data-action]');
    if (!btn) return;
    var action = btn.dataset.action;
    var id = parseInt(btn.dataset.id, 10);
    if (action === 'approve') {
      // 注册审核：通过（pending → active）
      api('/admin/users/' + id + '/status', { method: 'PUT', body: { status: 'active' } })
        .then(function () { loadUsers(); })
        .catch(function (err) { alert(err.message); });
    } else if (action === 'reject') {
      // 注册审核：拒绝（pending → disabled，可再启用）
      if (!confirm('确定拒绝用户「' + btn.dataset.name + '」的注册吗？\n拒绝后该用户无法登录，可随时再启用。')) return;
      api('/admin/users/' + id + '/status', { method: 'PUT', body: { status: 'disabled' } })
        .then(function () { loadUsers(); })
        .catch(function (err) { alert(err.message); });
    } else if (action === 'reset-usage') {
      // 重置今日 AI 分析次数
      if (!confirm('确定重置用户「' + btn.dataset.name + '」今日的 AI 分析次数吗？')) return;
      api('/admin/users/' + id + '/usage/reset', { method: 'POST' })
        .then(function () { loadUsers(); })
        .catch(function (err) { alert(err.message); });
    } else if (action === 'toggle') {
      var cur = btn.dataset.status;           // 当前状态
      var next = cur === 'active' ? 'disabled' : 'active';
      if (!confirm('确定要' + (next === 'disabled' ? '禁用' : '启用') + ' 该用户吗？')) return;
      api('/admin/users/' + id + '/status', { method: 'PUT', body: { status: next } })
        .then(function () { loadUsers(); })
        .catch(function (err) { alert(err.message); });
    } else if (action === 'delete') {
      if (!confirm('确定删除用户「' + btn.dataset.name + '」吗？\n此操作不可恢复，该用户的所有数据将被清除。')) return;
      api('/admin/users/' + id, { method: 'DELETE' })
        .then(function () { loadUsers(); })
        .catch(function (err) { alert(err.message); });
    }
  }

  // ============ 事件绑定 ============

  document.getElementById('usersTbody').addEventListener('click', onTableClick);
  document.getElementById('logoutBtn').addEventListener('click', function () {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem('chanalyzer_user_id');
    window.location.href = '/';
  });

  document.addEventListener('DOMContentLoaded', bootstrap);
})();
