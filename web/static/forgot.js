/**
 * 找回密码页面逻辑
 */
(function() {
  'use strict';

  const API_BASE = window.location.origin + '/api';

  const forgotForm = document.getElementById('forgotForm');
  const emailInput = document.getElementById('regEmail');
  const codeInput = document.getElementById('regEmailCode');
  const sendCodeBtn = document.getElementById('sendCodeBtn');
  const passwordInput = document.getElementById('newPassword');
  const passwordConfirmInput = document.getElementById('newPasswordConfirm');
  const passwordToggle = document.getElementById('newPasswordToggle');
  const submitBtn = document.getElementById('submitBtn');
  const btnText = document.getElementById('btnText');
  const spinner = document.getElementById('spinner');
  const errorMessage = document.getElementById('errorMessage');
  const captchaInput = document.getElementById('regCaptcha');
  const captchaImg = document.getElementById('captchaImg');

  let currentCaptchaId = null;

  // 显示/隐藏新密码
  passwordToggle.addEventListener('click', function() {
    passwordInput.type = passwordInput.type === 'password' ? 'text' : 'password';
  });

  function setLoading(loading) {
    submitBtn.disabled = loading;
    btnText.textContent = loading ? '重置中...' : '重置密码';
    spinner.style.display = loading ? 'block' : 'none';
  }

  function showError(message) {
    errorMessage.textContent = message;
    errorMessage.classList.add('show');
    setTimeout(() => errorMessage.classList.remove('show'), 5000);
  }
  function hideError() { errorMessage.classList.remove('show'); }

  /**
   * 加载图形验证码图片
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

  // 获取邮箱验证码(purpose=reset)+ 60s 倒计时
  let codeTimer = null;
  sendCodeBtn.addEventListener('click', async function() {
    hideError();
    const email = emailInput.value.trim();
    if (!email) { showError('请先填写注册邮箱'); return; }
    sendCodeBtn.disabled = true;
    sendCodeBtn.textContent = '发送中...';
    try {
      const resp = await fetch(`${API_BASE}/auth/send-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: email, purpose: 'reset' }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || '发送失败');
      let left = 60;
      sendCodeBtn.textContent = `${left}s 后重试`;
      codeTimer = setInterval(() => {
        left -= 1;
        if (left <= 0) {
          clearInterval(codeTimer);
          sendCodeBtn.disabled = false;
          sendCodeBtn.textContent = '获取验证码';
        } else {
          sendCodeBtn.textContent = `${left}s 后重试`;
        }
      }, 1000);
    } catch (e) {
      sendCodeBtn.disabled = false;
      sendCodeBtn.textContent = '获取验证码';
      showError(e.message || '发送失败,请稍后重试');
    }
  });

  // 表单提交:校验验证码 + 重置密码
  forgotForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    hideError();

    const email = emailInput.value.trim();
    const code = codeInput.value.trim();
    const password = passwordInput.value;
    const passwordConfirm = passwordConfirmInput.value;
    const captchaAnswer = captchaInput.value.trim();

    if (!email) { showError('请填写注册邮箱'); return; }
    if (!code) { showError('请输入邮箱验证码'); return; }
    if (password.length < 6) { showError('密码至少 6 位'); return; }
    if (password !== passwordConfirm) { showError('两次输入的密码不一致'); return; }
    if (!captchaAnswer) { showError('请输入图形验证码'); return; }
    if (!currentCaptchaId) { showError('图形验证码未加载，请点击图片刷新'); return; }

    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code, new_password: password, captcha_id: currentCaptchaId, captcha_answer: captchaAnswer }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        // 图形验证码为一次性,id 校验后即失效,失败需刷新图片
        if ((data.detail || '').includes('图形验证码')) {
          captchaInput.value = '';
          loadCaptcha();
        }
        throw new Error(data.detail || '重置失败');
      }

      btnText.textContent = '重置成功!';
      spinner.style.display = 'none';
      await new Promise(resolve => setTimeout(resolve, 800));
      // 跳登录页,带 reset 标记触发"已重置"提示并清旧 token
      window.location.href = '/?reset=1';
    } catch (error) {
      console.error('重置失败:', error);
      showError(error.message || '重置失败,请稍后重试');
    } finally {
      setLoading(false);
    }
  });

  emailInput.addEventListener('focus', hideError);
  codeInput.addEventListener('focus', hideError);
  passwordInput.addEventListener('focus', hideError);
  passwordConfirmInput.addEventListener('focus', hideError);
  captchaInput.addEventListener('focus', hideError);

  // 页面加载:拉取图形验证码
  loadCaptcha();
})();
