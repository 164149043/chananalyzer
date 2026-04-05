/**
 * ChanAnalyzer 前端数据交互模块
 *
 * 功能：
 * - 从后端 API 获取数据
 * - 处理扫描任务
 */

// API 基础地址
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? `http://${window.location.hostname}:8000/api`
    : '/api';

// 同时暴露到全局，供其他模块使用
window.API_BASE = API_BASE;

// ============ API 调用函数 ============

/**
 * 启动扫描任务
 */
async function startScan(options = {}) {
    try {
        const response = await fetch(`${API_BASE}/scan/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                buy_types: options.buyTypes || ['2', '3a', '3b'],
                sell_types: options.sellTypes || ['2s', '3a', '3b'],
                industry: options.industry,
                area: options.area,
                limit: options.limit || 100
            })
        });
        if (!response.ok) throw new Error('启动扫描失败');
        return await response.json();
    } catch (error) {
        console.error('启动扫描失败:', error);
        return null;
    }
}

/**
 * 获取扫描状态
 */
async function getScanStatus() {
    try {
        const response = await fetch(`${API_BASE}/scan/status`);
        if (!response.ok) throw new Error('获取扫描状态失败');
        return await response.json();
    } catch (error) {
        console.error('获取扫描状态失败:', error);
        return null;
    }
}

/**
 * 获取股票分析
 */
async function fetchStockAnalysis(code) {
    try {
        const response = await fetch(`${API_BASE}/stock/${code}`);
        if (!response.ok) throw new Error('获取股票分析失败');
        return await response.json();
    } catch (error) {
        console.error('获取股票分析失败:', error);
        return null;
    }
}

/**
 * 获取股票列表
 */
async function fetchStockList(filters = {}) {
    try {
        const params = new URLSearchParams();
        if (filters.industry) params.append('industry', filters.industry);
        if (filters.area) params.append('area', filters.area);
        if (filters.limit) params.append('limit', filters.limit);

        const response = await fetch(`${API_BASE}/stock/list?${params}`);
        if (!response.ok) throw new Error('获取股票列表失败');
        return await response.json();
    } catch (error) {
        console.error('获取股票列表失败:', error);
        return null;
    }
}

/**
 * 获取行业列表
 */
async function fetchIndustries() {
    try {
        const response = await fetch(`${API_BASE}/industries`);
        if (!response.ok) throw new Error('获取行业列表失败');
        return await response.json();
    } catch (error) {
        console.error('获取行业列表失败:', error);
        return null;
    }
}

// ============ 扫描状态管理 ============

/**
 * 更新扫描状态
 */
function updateScanStatus(status) {
    const scanBtn = document.querySelector('.action-btn.primary');
    if (!scanBtn) return;

    if (status.scanning) {
        scanBtn.innerHTML = `<span>⏳</span> 扫描中 ${status.progress}/${status.total}`;
        scanBtn.disabled = true;
    } else {
        scanBtn.innerHTML = `<span>🔄</span> 立即扫描全市场`;
        scanBtn.disabled = false;
    }
}

/**
 * 轮询扫描状态
 */
let scanPollingInterval = null;

function startScanPolling() {
    if (scanPollingInterval) return;

    scanPollingInterval = setInterval(async () => {
        const status = await getScanStatus();
        if (status) {
            updateScanStatus(status);

            // 扫描完成后停止轮询
            if (!status.scanning) {
                stopScanPolling();
            }
        }
    }, 3000);
}

function stopScanPolling() {
    if (scanPollingInterval) {
        clearInterval(scanPollingInterval);
        scanPollingInterval = null;
    }
}

// ============ 事件绑定 ============

/**
 * 初始化事件绑定
 */
function initEventBindings() {
    // 扫描按钮
    const scanBtn = document.querySelector('.action-btn.primary');
    if (scanBtn) {
        scanBtn.addEventListener('click', async () => {
            const result = await startScan();
            if (result) {
                startScanPolling();
            }
        });
    }

    // 导出按钮
    const exportBtn = document.querySelectorAll('.action-btn')[2];
    if (exportBtn) {
        exportBtn.addEventListener('click', () => {
            alert('导出功能开发中...');
        });
    }
}

// ============ 初始化 ============

/**
 * 页面加载完成后初始化
 */
document.addEventListener('DOMContentLoaded', () => {
    // 初始化事件绑定
    initEventBindings();
});
