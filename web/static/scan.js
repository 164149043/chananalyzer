/**
 * 买卖点扫描功能模块
 */

// API配置（复用 app.js 中已定义的 API_BASE）
if (typeof API_BASE === 'undefined') {
    window.API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
        ? `http://${window.location.hostname}:8000/api`
        : '/api';
}

// 买卖点类型映射 - 根据方向(买/卖)返回正确的中文名称
// 注意：Chan库买卖点共用类型值，靠 is_buy 区分方向
function getBsTypeLabel(type, isBuy) {
    const buyLabels = {
        '1': '一买',
        '1p': '一买衍生',
        '2': '二买',
        '3a': '三买A',
        '3b': '三买B',
        '2s': '类二买'
    };
    const sellLabels = {
        '1': '一卖',
        '1p': '一卖衍生',
        '2': '二卖',
        '3a': '三卖A',
        '3b': '三卖B',
        '2s': '二卖'
    };
    if (isBuy === false) {
        return sellLabels[type] || type;
    }
    return buyLabels[type] || type;
}

// 扫描状态管理
const scanState = {
    buy: {
        scanning: false,
        pollInterval: null,
        results: [],
        initialized: false
    },
    sell: {
        scanning: false,
        pollInterval: null,
        results: [],
        initialized: false
    }
};

/**
 * 启动买点扫描
 */
async function startBuyScan(types, limit) {
    try {
        const response = await AuthManager.fetch(`${window.API_BASE}/scan/buy/start`, {
            method: 'POST',
            body: {
                types: types,
                limit: parseInt(limit)
            }
        });
        if (!response.ok) throw new Error('启动买点扫描失败');
        return await response.json();
    } catch (error) {
        console.error('启动买点扫描失败:', error);
        throw error;
    }
}

/**
 * 启动卖点扫描
 */
async function startSellScan(types, limit) {
    try {
        const response = await AuthManager.fetch(`${window.API_BASE}/scan/sell/start`, {
            method: 'POST',
            body: {
                types: types,
                limit: parseInt(limit)
            }
        });
        if (!response.ok) throw new Error('启动卖点扫描失败');
        return await response.json();
    } catch (error) {
        console.error('启动卖点扫描失败:', error);
        throw error;
    }
}

/**
 * 获取买点扫描结果
 */
async function getBuyScanResults() {
    try {
        const response = await AuthManager.fetch(`${window.API_BASE}/scan/buy/results`);
        if (!response.ok) throw new Error('获取买点结果失败');
        return await response.json();
    } catch (error) {
        console.error('获取买点结果失败:', error);
        return { stocks: [] };
    }
}

/**
 * 获取卖点扫描结果
 */
async function getSellScanResults() {
    try {
        const response = await AuthManager.fetch(`${window.API_BASE}/scan/sell/results`);
        if (!response.ok) throw new Error('获取卖点结果失败');
        return await response.json();
    } catch (error) {
        console.error('获取卖点结果失败:', error);
        return { stocks: [] };
    }
}

/**
 * 获取买点扫描状态
 */
async function getBuyScanStatus() {
    try {
        const response = await AuthManager.fetch(`${window.API_BASE}/scan/buy/status`);
        if (!response.ok) throw new Error('获取买点状态失败');
        return await response.json();
    } catch (error) {
        console.error('获取买点状态失败:', error);
        return null;
    }
}

/**
 * 获取卖点扫描状态
 */
async function getSellScanStatus() {
    try {
        const response = await AuthManager.fetch(`${window.API_BASE}/scan/sell/status`);
        if (!response.ok) throw new Error('获取卖点状态失败');
        return await response.json();
    } catch (error) {
        console.error('获取卖点状态失败:', error);
        return null;
    }
}

/**
 * 更新进度条
 */
function updateProgress(direction, status) {
    const prefix = direction === 'buy' ? 'buy' : 'sell';
    const progressBar = document.querySelector(`#${prefix}-scan-progress .progress-fill`);
    const progressStatus = document.querySelector(`#${prefix}-scan-progress .progress-status`);
    const progressDetail = document.querySelector(`#${prefix}-scan-progress .progress-detail`);

    if (progressBar) {
        // 重置进度条颜色（蓝色渐变）
        progressBar.style.background = 'linear-gradient(90deg, #3b82f6, #10b981)';

        if (status.total > 0) {
            const percent = Math.min(100, (status.progress / status.total * 100));
            progressBar.style.width = `${percent}%`;
        } else {
            // 还没有获取 total，显示等待状态
            progressBar.style.width = '0%';
        }
    }

    if (progressStatus) {
        if (status.scanning) {
            if (status.total > 0) {
                progressStatus.textContent = `扫描中 ${status.progress}/${status.total}`;
            } else {
                progressStatus.textContent = status.message || '准备中...';
            }
        } else {
            progressStatus.textContent = status.message || '扫描完成';
        }
    }

    if (progressDetail) {
        // 重置颜色
        progressDetail.style.color = '#607080';
        progressDetail.textContent = status.scanning
            ? `已找到 ${status.found} 只股票`
            : status.message || `已找到 ${status.found} 只股票`;
    }
}

/**
 * 渲染结果表格
 */
function renderResultsTable(direction, stocks) {
    const prefix = direction === 'buy' ? 'buy' : 'sell';
    const tbody = document.querySelector(`#${prefix}-results-table tbody`);
    const emptyState = document.querySelector(`#${prefix}-empty-state`);
    const table = document.querySelector(`#${prefix}-results-table`);

    if (!tbody || !table) return;

    // 清空表格
    tbody.innerHTML = '';

    if (!stocks || stocks.length === 0) {
        table.classList.add('hidden');
        if (emptyState) emptyState.classList.remove('hidden');
        return;
    }

    table.classList.remove('hidden');
    if (emptyState) emptyState.classList.add('hidden');

    // 按最新信号日期排序 (最近的在前)
    const sortedStocks = [...stocks].sort((a, b) => {
        if (!a.latest_signal || !b.latest_signal) return 0;
        const dateA = new Date(a.latest_signal.date);
        const dateB = new Date(b.latest_signal.date);
        return dateB - dateA;
    });

    sortedStocks.forEach(stock => {
        const tr = document.createElement('tr');
        const signal = stock.latest_signal;
        if (!signal) return;

        const typeLabel = getBsTypeLabel(signal.type, signal.is_buy);
        const typeClass = direction === 'buy' ? 'buy' : 'sell';

        // 使用data-label属性，便于移动端卡片式显示
        tr.innerHTML = `
            <td class="code" data-label="股票代码">${stock.code}</td>
            <td data-label="股票名称">${stock.name || ''}</td>
            <td data-label="当前价格">${stock.current_price ? stock.current_price.toFixed(2) : '--'}</td>
            <td data-label="买点类型"><span class="bs-type ${typeClass}">${typeLabel}</span></td>
            <td data-label="信号日期">${signal.date}</td>
            <td data-label="信号价格">${signal.price ? signal.price.toFixed(2) : '--'}</td>
        `;

        tbody.appendChild(tr);
    });
}

/**
 * 更新统计数据
 */
function updateStats(direction, results) {
    const prefix = direction === 'buy' ? 'buy' : 'sell';

    // 统计各类型数量
    const stats = { '1': 0, '1p': 0, '2': 0, '3a': 0, '3b': 0, '2s': 0 };
    let total = 0;

    if (results && results.stocks) {
        results.stocks.forEach(stock => {
            stock.signals.forEach(signal => {
                const type = signal.type;
                if (type in stats) {
                    stats[type]++;
                }
                total++;
            });
        });
    }

    // 更新统计显示
    const totalElement = document.querySelector(`#${prefix}-scan-stats .stat-item:first-child .stat-value`);
    if (totalElement) {
        totalElement.textContent = results?.stocks?.length || 0;
    }

    if (direction === 'buy') {
        const buy1 = document.querySelector(`#${prefix}-scan-stats .buy-1`);
        const buy2 = document.querySelector(`#${prefix}-scan-stats .buy-2`);
        const buy3 = document.querySelector(`#${prefix}-scan-stats .buy-3`);
        if (buy1) buy1.textContent = stats['1'] + stats['1p'];
        if (buy2) buy2.textContent = stats['2'];
        if (buy3) buy3.textContent = stats['3a'] + stats['3b'];
    } else {
        const sell2s = document.querySelector(`#${prefix}-scan-stats .sell-2s`);
        if (sell2s) sell2s.textContent = stats['2s'];
    }

    // 更新时间
    const timeElement = document.querySelector(`#${prefix}-scan-stats .time`);
    if (timeElement && results?.cache_time) {
        const time = new Date(results.cache_time);
        const hours = time.getHours().toString().padStart(2, '0');
        const minutes = time.getMinutes().toString().padStart(2, '0');
        timeElement.textContent = `${hours}:${minutes}`;
    }
}

/**
 * 轮询扫描状态
 */
function pollScanStatus(direction) {
    const prefix = direction === 'buy' ? 'buy' : 'sell';

    if (scanState[direction].pollInterval) {
        return; // 已在轮询中
    }

    scanState[direction].pollInterval = setInterval(async () => {
        const status = direction === 'buy'
            ? await getBuyScanStatus()
            : await getSellScanStatus();

        if (!status) return;

        updateProgress(direction, status);

        // 检查是否有错误
        if (status.error) {
            clearInterval(scanState[direction].pollInterval);
            scanState[direction].pollInterval = null;
            scanState[direction].scanning = false;

            // 显示错误提示
            showErrorMessage(direction, status.error);

            // 重置按钮状态
            const btn = document.querySelector(`#${prefix}-scan-btn`);
            if (btn) {
                btn.innerHTML = `<span>🔍</span> ${direction === 'buy' ? '开始扫描买点' : '开始扫描卖点'}`;
                btn.disabled = false;
            }
            return;
        }

        // 扫描完成
        if (!status.scanning) {
            clearInterval(scanState[direction].pollInterval);
            scanState[direction].pollInterval = null;
            scanState[direction].scanning = false;

            // 获取结果并显示
            const results = direction === 'buy'
                ? await getBuyScanResults()
                : await getSellScanResults();

            if (results) {
                renderResultsTable(direction, results.stocks);
                updateStats(direction, results);
            }

            // 重置按钮状态
            const btn = document.querySelector(`#${prefix}-scan-btn`);
            if (btn) {
                btn.innerHTML = `<span>🔍</span> ${direction === 'buy' ? '开始扫描买点' : '开始扫描卖点'}`;
                btn.disabled = false;
            }
        }
    }, 1000);
}

/**
 * 显示错误消息
 */
function showErrorMessage(direction, errorMsg) {
    const prefix = direction === 'buy' ? 'buy' : 'sell';
    const progressDetail = document.querySelector(`#${prefix}-scan-progress .progress-detail`);
    const progressBar = document.querySelector(`#${prefix}-scan-progress .progress-fill`);

    if (progressBar) {
        progressBar.style.width = '100%';
        progressBar.style.background = '#e74c3c'; // 红色表示错误
    }

    if (progressDetail) {
        progressDetail.textContent = `扫描失败: ${errorMsg}`;
        progressDetail.style.color = '#e74c3c';
    }

    // 同时弹出提示
    alert(`${direction === 'buy' ? '买点' : '卖点'}扫描失败: ${errorMsg}`);
}

/**
 * 初始化买点扫描页面
 */
async function initBuyScanPage() {
    // 防止重复初始化
    if (scanState.buy.initialized) return;
    scanState.buy.initialized = true;

    const btn = document.getElementById('buy-scan-btn');
    if (!btn) {
        scanState.buy.initialized = false;
        return;
    }

    btn.addEventListener('click', async () => {
        if (scanState.buy.scanning) return;

        // 获取选中的买点类型
        const checkboxes = document.querySelectorAll('#buyTypesGroup input:checked');
        const types = Array.from(checkboxes).map(cb => cb.value);

        if (types.length === 0) {
            alert('请至少选择一种买点类型');
            return;
        }

        const limit = document.getElementById('buy-limit-select').value;

        // 更新按钮状态
        scanState.buy.scanning = true;
        btn.disabled = true;
        btn.innerHTML = '<span>⏳</span> 扫描中...';

        try {
            // 启动扫描
            await startBuyScan(types, limit);
            // 开始轮询
            pollScanStatus('buy');
        } catch (error) {
            // 启动失败，重置状态
            scanState.buy.scanning = false;
            btn.disabled = false;
            btn.innerHTML = '<span>🔍</span> 开始扫描买点';
            showErrorMessage('buy', error.message || '启动扫描失败');
        }
    });

    // 加载历史结果
    //await loadBuyScanHistory();

    // 检查是否有正在进行的扫描
    const status = await getBuyScanStatus();
    if (status && status.scanning) {
        scanState.buy.scanning = true;
        btn.disabled = true;
        btn.innerHTML = '<span>⏳</span> 扫描中...';
        pollScanStatus('buy');
    }
}

/**
 * 初始化卖点扫描页面
 */
async function initSellScanPage() {
    // 防止重复初始化
    if (scanState.sell.initialized) return;
    scanState.sell.initialized = true;

    const btn = document.getElementById('sell-scan-btn');
    if (!btn) {
        scanState.sell.initialized = false;
        return;
    }

    btn.addEventListener('click', async () => {
        if (scanState.sell.scanning) return;

        // 获取选中的卖点类型
        const checkboxes = document.querySelectorAll('#sellTypesGroup input:checked');
        const types = Array.from(checkboxes).map(cb => cb.value);

        if (types.length === 0) {
            alert('请至少选择一种卖点类型');
            return;
        }

        const limit = document.getElementById('sell-limit-select').value;

        // 更新按钮状态
        scanState.sell.scanning = true;
        btn.disabled = true;
        btn.innerHTML = '<span>⏳</span> 扫描中...';

        try {
            // 启动扫描
            await startSellScan(types, limit);
            // 开始轮询
            pollScanStatus('sell');
        } catch (error) {
            // 启动失败，重置状态
            scanState.sell.scanning = false;
            btn.disabled = false;
            btn.innerHTML = '<span>🔍</span> 开始扫描卖点';
            showErrorMessage('sell', error.message || '启动扫描失败');
        }
    });

    // 加载历史结果
    //await loadSellScanHistory();

    // 检查是否有正在进行的扫描
    const status = await getSellScanStatus();
    if (status && status.scanning) {
        scanState.sell.scanning = true;
        btn.disabled = true;
        btn.innerHTML = '<span>⏳</span> 扫描中...';
        pollScanStatus('sell');
    }
}

/**
 * 加载历史买点扫描结果
 */
async function loadBuyScanHistory() {
    const results = await getBuyScanResults();
    if (results && results.stocks) {
        renderResultsTable('buy', results.stocks);
        updateStats('buy', results);

        // 更新时间显示
        const status = await getBuyScanStatus();
        if (status && status.last_scan_time) {
            const time = new Date(status.last_scan_time);
            const hours = time.getHours().toString().padStart(2, '0');
            const minutes = time.getMinutes().toString().padStart(2, '0');
            const timeElement = document.querySelector('#buy-scan-stats .time');
            if (timeElement) timeElement.textContent = `${hours}:${minutes}`;
        }
    }
}

/**
 * 加载历史卖点扫描结果
 */
async function loadSellScanHistory() {
    const results = await getSellScanResults();
    if (results && results.stocks) {
        renderResultsTable('sell', results.stocks);
        updateStats('sell', results);

        // 更新时间显示
        const status = await getSellScanStatus();
        if (status && status.last_scan_time) {
            const time = new Date(status.last_scan_time);
            const hours = time.getHours().toString().padStart(2, '0');
            const minutes = time.getMinutes().toString().padStart(2, '0');
            const timeElement = document.querySelector('#sell-scan-stats .time');
            if (timeElement) timeElement.textContent = `${hours}:${minutes}`;
        }
    }
}

// 知识卡片功能已移除
