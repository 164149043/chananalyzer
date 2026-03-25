/**
 * 用户认证模块
 *
 * 处理用户会话、Token管理和API请求认证
 */

const STORAGE_KEY = 'chanalyzer_token';
const USER_ID_KEY = 'chanalyzer_user_id';

// 当前页面路径，用于登录后返回
const currentPath = window.location.pathname;

/**
 * 认证管理器
 */
const AuthManager = {
    token: null,
    userId: null,

    /**
     * 初始化认证状态
     */
    async init() {
        // 从localStorage读取
        this.token = localStorage.getItem(STORAGE_KEY);
        this.userId = localStorage.getItem(USER_ID_KEY);

        // 如果没有token，跳转到登录页
        if (!this.token) {
            this.redirectToLogin();
            return;
        }

        // 验证现有会话
        await this.verifySession();
    },

    /**
     * 检查是否已登录
     */
    isLoggedIn() {
        return !!this.token;
    },

    /**
     * 跳转到登录页
     */
    redirectToLogin() {
        // 如果当前不在登录页面，跳转到登录页
        if (!currentPath.includes('login.html')) {
            window.location.href = '/static/login.html';
        }
    },

    /**
     * 登出
     */
    logout() {
        this.clear();
        window.location.href = '/static/login.html';
    },

    /**
     * 创建新会话
     */
    async createSession() {
        try {
            const response = await fetch(`${window.API_BASE}/auth/session`);
            if (!response.ok) {
                throw new Error('创建会话失败');
            }
            const data = await response.json();
            this.token = data.token;
            this.userId = data.user_id;
            this.save();
            return data;
        } catch (error) {
            console.error('创建会话失败:', error);
            throw error;
        }
    },

    /**
     * 验证现有会话
     */
    async verifySession() {
        try {
            const response = await fetch(`${window.API_BASE}/auth/session`, {
                headers: this.getAuthHeaders()
            });
            if (!response.ok) {
                // Token无效，创建新会话
                await this.createSession();
                return;
            }
            const data = await response.json();
            // 更新token（可能被刷新）
            this.token = data.token;
            this.userId = data.user_id;
            this.save();
        } catch (error) {
            console.error('验证会话失败:', error);
            await this.createSession();
        }
    },

    /**
     * 刷新会话
     */
    async refreshSession() {
        try {
            const response = await fetch(`${window.API_BASE}/auth/refresh`, {
                headers: this.getAuthHeaders()
            });
            if (!response.ok) {
                throw new Error('刷新会话失败');
            }
            const data = await response.json();
            this.token = data.token;
            this.userId = data.user_id;
            this.save();
            return data;
        } catch (error) {
            console.error('刷新会话失败:', error);
            // 尝试创建新会话
            return await this.createSession();
        }
    },

    /**
     * 保存到本地存储
     */
    save() {
        if (this.token) {
            localStorage.setItem(STORAGE_KEY, this.token);
        }
        if (this.userId) {
            localStorage.setItem(USER_ID_KEY, this.userId);
        }
    },

    /**
     * 清除会话
     */
    clear() {
        this.token = null;
        this.userId = null;
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(USER_ID_KEY);
    },

    /**
     * 获取认证请求头
     */
    getAuthHeaders() {
        const headers = {
            'Content-Type': 'application/json'
        };
        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }
        return headers;
    },

    /**
     * 带认证的fetch请求
     */
    async fetch(url, options = {}) {
        // 合并headers
        const headers = {
            ...this.getAuthHeaders(),
            ...(options.headers || {})
        };

        // 处理非JSON请求（如文件上传）
        if (options.body && !(options.body instanceof String) && !(options.body instanceof FormData)) {
            // 如果body是对象且不是FormData，序列化为JSON
            if (typeof options.body === 'object') {
                options.body = JSON.stringify(options.body);
            }
        }

        const response = await fetch(url, {
            ...options,
            headers
        });

        // 处理401未授权错误
        if (response.status === 401) {
            // Token 失效，跳转到登录页
            this.logout();
            throw new Error('会话已过期，请重新登录');
        }

        return response;
    },

    /**
     * 获取用户ID
     */
    getUserId() {
        return this.userId;
    },

    /**
     * 获取Token
     */
    getToken() {
        return this.token;
    }
};

// 导出到全局
window.AuthManager = AuthManager;

// 页面加载时自动初始化
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => AuthManager.init());
} else {
    AuthManager.init();
}
