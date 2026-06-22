/**
 * 注册页面逻辑
 */
(function() {
  'use strict';

  const API_BASE = window.location.origin + '/api';
  const STORAGE_KEY = 'chanalyzer_token';
  const USER_ID_KEY = 'chanalyzer_user_id';

  const registerForm = document.getElementById('registerForm');
  const usernameInput = document.getElementById('regUsername');
  const passwordInput = document.getElementById('regPassword');
  const passwordConfirmInput = document.getElementById('regPasswordConfirm');
  const captchaInput = document.getElementById('regCaptcha');
  const captchaImg = document.getElementById('captchaImg');
  const submitBtn = document.getElementById('submitBtn');
  const btnText = document.getElementById('btnText');
  const spinner = document.getElementById('spinner');
  const passwordToggle = document.getElementById('regPasswordToggle');
  const errorMessage = document.getElementById('errorMessage');

  let currentCaptchaId = null;

  /**
   * 加载验证码图片
   */
  async function loadCaptcha() {
    try {
      const resp = await fetch(`${API_BASE}/auth/captcha`);
      if (!resp.ok) throw new Error();
      const data = await resp.json();
      currentCaptchaId = data.captcha_id;
      captchaImg.src = data.image;
    } catch (e) {
      captchaImg.alt = '验证码加载失败';
    }
  }

  captchaImg.addEventListener('click', loadCaptcha);

  /**
   * 显示/隐藏密码
   */
  passwordToggle.addEventListener('click', function() {
    passwordInput.type = passwordInput.type === 'password' ? 'text' : 'password';
  });

  function setLoading(loading) {
    submitBtn.disabled = loading;
    btnText.textContent = loading ? '注册中...' : '注册';
    spinner.style.display = loading ? 'block' : 'none';
  }

  function showError(message) {
    errorMessage.textContent = message;
    errorMessage.classList.add('show');
    setTimeout(() => errorMessage.classList.remove('show'), 5000);
  }

  function hideError() {
    errorMessage.classList.remove('show');
  }

  /**
   * 表单提交
   */
  registerForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    hideError();

    const username = usernameInput.value.trim();
    const password = passwordInput.value;
    const passwordConfirm = passwordConfirmInput.value;
    const captchaAnswer = captchaInput.value.trim();

    if (!/^[A-Za-z0-9_]{3,32}$/.test(username)) {
      showError('用户名为 3-32 位字母、数字或下划线');
      return;
    }
    if (password.length < 6) {
      showError('密码至少 6 位');
      return;
    }
    if (password !== passwordConfirm) {
      showError('两次输入的密码不一致');
      return;
    }
    if (!captchaAnswer) {
      showError('请输入验证码');
      return;
    }
    if (!currentCaptchaId) {
      showError('验证码未加载，请点击图片刷新');
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username, password,
          captcha_id: currentCaptchaId,
          captcha_answer: captchaAnswer,
        })
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        // 验证码失败后刷新验证码
        if ((data.detail || '').includes('验证码')) {
          captchaInput.value = '';
          loadCaptcha();
        }
        throw new Error(data.detail || '注册失败');
      }

      // 注册成功，保存登录信息并跳转
      localStorage.setItem(STORAGE_KEY, data.token);
      localStorage.setItem(USER_ID_KEY, data.user_id);

      btnText.textContent = '注册成功！';
      await new Promise(resolve => setTimeout(resolve, 500));
      window.location.href = '/app';

    } catch (error) {
      console.error('注册失败:', error);
      showError(error.message || '注册失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  });

  usernameInput.addEventListener('focus', hideError);
  passwordInput.addEventListener('focus', hideError);
  passwordConfirmInput.addEventListener('focus', hideError);
  captchaInput.addEventListener('focus', hideError);

  /**
   * 页面加载：已登录则跳转应用，否则加载验证码
   */
  document.addEventListener('DOMContentLoaded', function() {
    if (localStorage.getItem(STORAGE_KEY)) {
      window.location.href = '/app';
      return;
    }
    loadCaptcha();
  });

})();
