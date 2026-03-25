/**
 * 登录页面逻辑
 */
(function() {
  'use strict';

  // 配置
  const API_BASE = window.location.origin + '/api';
  const STORAGE_KEY = 'chanalyzer_token';
  const USER_ID_KEY = 'chanalyzer_user_id';

  // DOM 元素
  const loginForm = document.getElementById('loginForm');
  const usernameInput = document.getElementById('username');
  const passwordInput = document.getElementById('password');
  const submitBtn = document.getElementById('submitBtn');
  const btnText = document.getElementById('btnText');
  const spinner = document.getElementById('spinner');
  const passwordToggle = document.getElementById('passwordToggle');
  const errorMessage = document.getElementById('errorMessage');

  /**
   * 显示/隐藏密码
   */
  passwordToggle.addEventListener('click', function() {
    const type = passwordInput.type === 'password' ? 'text' : 'password';
    passwordInput.type = type;

    // 切换图标
    if (type === 'text') {
      passwordToggle.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="20" height="20">
          <path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      `;
    } else {
      passwordToggle.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="20" height="20">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
        </svg>
      `;
    }
  });

  /**
   * 设置加载状态
   */
  function setLoading(loading) {
    submitBtn.disabled = loading;
    if (loading) {
      btnText.textContent = '登录中...';
      spinner.style.display = 'block';
    } else {
      btnText.textContent = '登录';
      spinner.style.display = 'none';
    }
  }

  /**
   * 显示错误信息
   */
  function showError(message) {
    errorMessage.textContent = message;
    errorMessage.classList.add('show');
    setTimeout(() => {
      errorMessage.classList.remove('show');
    }, 5000);
  }

  /**
   * 隐藏错误信息
   */
  function hideError() {
    errorMessage.classList.remove('show');
  }

  /**
   * 保存登录信息
   */
  function saveLoginInfo(token, userId) {
    localStorage.setItem(STORAGE_KEY, token);
    localStorage.setItem(USER_ID_KEY, userId);
  }

  /**
   * 检查是否已登录
   * @param {boolean} force - 是否强制显示登录页（忽略已登录状态）
   */
  function checkLoggedIn(force = false) {
    const token = localStorage.getItem(STORAGE_KEY);
    if (token && !force) {
      // 已登录，跳转到首页
      window.location.href = '/static/index.html';
      return true;
    }
    return false;
  }

  /**
   * 获取 URL 参数
   */
  function getUrlParam(name) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(name);
  }

  /**
   * 登录
   */
  async function login(username, password) {
    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ username, password })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || '登录失败，请检查账号密码');
      }

      return data;
    } catch (error) {
      throw error;
    }
  }

  /**
   * 表单提交处理
   */
  loginForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    hideError();

    const username = usernameInput.value.trim();
    const password = passwordInput.value;

    if (!username || !password) {
      showError('请输入用户名和密码');
      return;
    }

    setLoading(true);

    try {
      const data = await login(username, password);

      // 保存登录信息
      saveLoginInfo(data.token, data.user_id);

      // 延迟跳转，让用户看到成功状态
      btnText.textContent = '登录成功！';
      await new Promise(resolve => setTimeout(resolve, 500));

      // 跳转到首页
      window.location.href = '/static/index.html';

    } catch (error) {
      console.error('登录失败:', error);
      showError(error.message || '登录失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  });

  /**
   * 输入框获取焦点时隐藏错误
   */
  usernameInput.addEventListener('focus', hideError);
  passwordInput.addEventListener('focus', hideError);

  /**
   * 页面加载时检查登录状态
   */
  document.addEventListener('DOMContentLoaded', function() {
    // 检查是否强制显示登录页（URL 中有 force 或 logout 参数）
    const forceLogin = getUrlParam('force') === 'true' || getUrlParam('logout') === 'true';

    // 如果有 logout 参数，清除现有的登录信息
    if (getUrlParam('logout') === 'true') {
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(USER_ID_KEY);
    }

    checkLoggedIn(forceLogin);
  });

})();
