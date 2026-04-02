/**
 * 个股分析页面交互脚本
 */

// API_BASE is already defined in app.js, using the shared reference

// 当前分析状态
let isAnalyzing = false;
let eventSource = null;

// 打字机效果定时器存储
const typewriterIntervals = {
    analystA: null,
    analystB: null,
    decision: null
};

// ============ 打字机效果 ============

/**
 * 检查页面是否可见
 */
function isPageVisible() {
    // Page Visibility API 检测页面是否在当前可见标签页
    return !document.hidden;
}

/**
 * 打字机效果 - 逐字符显示文本
 * @param {string} elementId - 目标元素ID
 * @param {string} text - 要显示的文本
 * @param {number} speed - 每个字符的间隔时间(ms)
 * @param {string} storageKey - 定时器存储键
 */
function typewriterEffect(elementId, text, speed = 30, storageKey = '') {
    const el = document.getElementById(elementId);
    if (!el) return;

    // 清除之前的打字机效果
    if (storageKey && typewriterIntervals[storageKey]) {
        clearTimeout(typewriterIntervals[storageKey]);
        typewriterIntervals[storageKey] = null;
    }

    // 移除占位符或加载状态
    const placeholder = el.querySelector('.output-placeholder, .loading');
    if (placeholder) {
        placeholder.remove();
    }

    // 标记有内容
    el.dataset.hasContent = 'true';

    // 如果页面不可见（后台标签页），直接显示完整文本，跳过打字机效果
    if (!isPageVisible()) {
        el.textContent = text;
        applyHighlighting(el);
        return;
    }

    let index = 0;
    el.textContent = '';

    function type() {
        // 如果页面变成不可见，立即显示剩余文本
        if (!isPageVisible()) {
            el.textContent = text;
            applyHighlighting(el);
            return;
        }

        if (index < text.length) {
            // 每次显示1-2个中文字符，让效果更流畅
            const charsPerStep = /[\u4e00-\u9fa5]/.test(text[index]) ? 2 : 3;
            const endIndex = Math.min(index + charsPerStep, text.length);
            el.textContent += text.slice(index, endIndex);
            index = endIndex;

            // 随机化间隔时间，让打字效果更自然
            const randomSpeed = speed + (Math.random() * 20 - 10);
            const timer = setTimeout(type, randomSpeed);

            if (storageKey) {
                typewriterIntervals[storageKey] = timer;
            }
        } else {
            // 打字完成后应用高亮效果
            applyHighlighting(el);
        }
    }

    type();
}

/**
 * 应用高亮效果到文本
 * @param {HTMLElement} element - 目标元素
 */
function applyHighlighting(element) {
    const parentClass = element.parentElement?.className || '';
    const html = element.innerHTML;

    // 数字高亮
    const highlightedHtml = html.replace(/(\d+\.?\d*)%/g, '<span class="num-highlight">$1</span>')
                           .replace(/(\d+\.?\d*)(?=[^0-9]|$)/g, '<span class="num-highlight">$1</span>');

    // 关键词高亮
    const keywordMapping = [
        { pattern: /(一买|二买|三买|一卖|二卖|三卖)/g, className: 'keyword-buy' },
        { pattern: /(买点|卖点|做多|做空)/g, className: 'keyword' },
        { pattern: /(建议|推荐|操作|风险|注意)/g, className: 'keyword' }
    ];

    let result = highlightedHtml;
    keywordMapping.forEach(({ pattern, className }) => {
        result = result.replace(pattern, `<span class="${className}">$1</span>`);
    });

    // 决策者特殊处理
    if (parentClass.includes('decision-maker-section')) {
        // 建议买入/卖出/持有
        result = result.replace(/(建议买入|推荐买入|可以考虑买入)/gi,
            '<span class="recommendation recommend-buy">$1</span>');
        result = result.replace(/(建议卖出|推荐卖出|可以考虑卖出)/gi,
            '<span class="recommendation recommend-sell">$1</span>');
        result = result.replace(/(持有|观望|等待|谨慎)/gi,
            '<span class="recommendation recommend-hold">$1</span>');
    }

    element.innerHTML = result;
}

/**
 * 停止所有打字机效果
 */
function stopAllTypewriters() {
    Object.keys(typewriterIntervals).forEach(key => {
        if (typewriterIntervals[key]) {
            clearTimeout(typewriterIntervals[key]);
            typewriterIntervals[key] = null;
        }
    });
}

// ============ 温度滑块控制 ============

/**
 * 获取当前温度配置
 */
function getTemperatures() {
    return {
        analyst_a: parseFloat(document.getElementById('temp-slider-a')?.value || 0.4),
        analyst_b: parseFloat(document.getElementById('temp-slider-b')?.value || 0.7),
        decision_maker: parseFloat(document.getElementById('temp-slider-d')?.value || 0.3)
    };
}

// ============ UI 更新函数 ============

/**
 * 清空输出区域
 */
function clearOutputs() {
    // 停止所有打字机效果
    stopAllTypewriters();

    const outputs = ['analyst-a-output', 'analyst-b-output', 'decision-output'];
    outputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.innerHTML = '<div class="output-placeholder">等待分析...</div>';
            el.removeAttribute('data-has-content');
        }
    });

    // 隐藏耗时统计
    const timingInfo = document.getElementById('timing-info');
    if (timingInfo) {
        timingInfo.style.display = 'none';
    }
}

/**
 * 显示分析师加载状态
 */
function showAnalystLoading(analystId) {
    const outputId = analystId === 0 ? 'analyst-a-output' : 'analyst-b-output';
    const storageKey = analystId === 0 ? 'analystA' : 'analystB';

    // 停止该分析区域的打字机效果
    if (typewriterIntervals[storageKey]) {
        clearTimeout(typewriterIntervals[storageKey]);
        typewriterIntervals[storageKey] = null;
    }

    const el = document.getElementById(outputId);
    if (el) {
        el.innerHTML = '<div class="loading">正在分析中...</div>';
        el.removeAttribute('data-has-content');
    }
}

/**
 * 完成分析师分析 - 使用打字机效果显示
 */
function completeAnalyst(analystId, opinion) {
    const outputId = analystId === 0 ? 'analyst-a-output' : 'analyst-b-output';
    const storageKey = analystId === 0 ? 'analystA' : 'analystB';

    // 使用打字机效果显示分析结果（加快速度：10ms）
    typewriterEffect(outputId, opinion, 10, storageKey);
}

/**
 * 显示决策者加载状态
 */
function showDecisionLoading() {
    // 停止决策区域的打字机效果
    if (typewriterIntervals.decision) {
        clearTimeout(typewriterIntervals.decision);
        typewriterIntervals.decision = null;
    }

    const el = document.getElementById('decision-output');
    if (el) {
        el.innerHTML = '<div class="loading">正在综合决策...</div>';
        el.removeAttribute('data-has-content');
    }
}

/**
 * 完成决策 - 使用打字机效果显示
 */
function completeDecision(decision) {
    // 使用打字机效果显示决策结果（加快速度：10ms）
    typewriterEffect('decision-output', decision, 10, 'decision');
}

/**
 * 更新耗时统计
 */
function updateTiming(timing) {
    const timingInfo = document.getElementById('timing-info');
    if (timingInfo) {
        timingInfo.style.display = 'block';

        const analystsTime = document.getElementById('analysts-time');
        const decisionTime = document.getElementById('decision-time');
        const totalTime = document.getElementById('total-time');

        if (analystsTime) analystsTime.textContent = timing.analysts?.toFixed(1) || '0.0';
        if (decisionTime) decisionTime.textContent = timing.decision_maker?.toFixed(1) || '0.0';
        if (totalTime) totalTime.textContent = timing.total?.toFixed(1) || '0.0';
    }
}

/**
 * 设置分析按钮状态
 */
function setAnalyzingState(analyzing) {
    const btn = document.getElementById('analyze-btn');
    const codeInput = document.getElementById('stock-code');

    if (btn) {
        btn.disabled = analyzing;
        btn.innerHTML = analyzing
            ? '<span>⏳</span> 分析中...'
            : '<span>🚀</span> 开始分析';
    }

    if (codeInput) {
        codeInput.disabled = analyzing;
    }

    isAnalyzing = analyzing;
}

// ============ SSE 分析处理 ============

/**
 * 启动分析
 */
async function startAnalysis() {
    if (isAnalyzing) return;

    const codeInput = document.getElementById('stock-code');
    const code = codeInput?.value?.trim();

    if (!code) {
        alert('请输入股票代码');
        return;
    }

    // 验证股票代码格式
    if (!/^\d{6}$/.test(code)) {
        alert('股票代码格式不正确，请输入6位数字');
        return;
    }

    // 清空之前的结果
    clearOutputs();
    setAnalyzingState(true);

    // 关闭之前的 SSE 连接
    if (eventSource) {
        eventSource.close();
    }

    try {
        const temperatures = getTemperatures();

        // 使用 fetch POST 启动分析，获取 SSE URL
        const response = await fetch(`${API_BASE}/stock/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                code: code,
                temperatures: temperatures
            })
        });

        if (!response.ok) {
            throw new Error('分析请求失败');
        }

        // 处理 SSE 流
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        handleSSEEvent(data);
                    } catch (e) {
                        console.error('解析 SSE 数据失败:', e);
                    }
                }
            }
        }

    } catch (error) {
        console.error('分析失败:', error);
        alert('分析失败: ' + error.message);
        setAnalyzingState(false);
    }
}

/**
 * 处理 SSE 事件
 */
function handleSSEEvent(data) {
    switch (data.event) {
        case 'analyst_start':
            showAnalystLoading(data.analyst_id);
            break;

        case 'analyst_done':
            // 分析完成，使用打字机效果显示结果
            completeAnalyst(data.analyst_id, data.opinion);
            break;

        case 'decision_start':
            showDecisionLoading();
            break;

        case 'decision_done':
            // 决策完成，使用打字机效果显示结果
            completeDecision(data.decision);
            updateTiming(data.timing);
            setAnalyzingState(false);
            break;

        case 'error':
            alert('分析错误: ' + data.message);
            setAnalyzingState(false);
            break;

        case 'complete':
            setAnalyzingState(false);
            break;
    }
}

// ============ 初始化 ============

/**
 * 初始化温度滑块
 */
function initTemperatureSliders() {
    const sliderConfigs = [
        { id: 'temp-slider-a', valueId: 'temp-value-a' },
        { id: 'temp-slider-b', valueId: 'temp-value-b' },
        { id: 'temp-slider-d', valueId: 'temp-value-d' }
    ];

    sliderConfigs.forEach(config => {
        const slider = document.getElementById(config.id);
        const valueDisplay = document.getElementById(config.valueId);

        if (slider && valueDisplay) {
            // 设置初始值和颜色
            const initialValue = parseFloat(slider.value);
            valueDisplay.textContent = initialValue.toFixed(1);
            updateTempValueColor(valueDisplay, initialValue);

            // 绑定 input 事件
            slider.oninput = function() {
                const val = parseFloat(this.value);
                const display = document.getElementById(config.valueId);
                if (display) {
                    display.textContent = val.toFixed(1);
                    updateTempValueColor(display, val);
                }
            };
        }
    });
}

/**
 * 更新温度值颜色
 * @param {HTMLElement} element - 温度值显示元素
 * @param {number} value - 温度值
 */
function updateTempValueColor(element, value) {
    // 移除所有颜色属性
    element.removeAttribute('data-temp');

    // 根据温度值设置颜色
    if (value <= 0.4) {
        element.setAttribute('data-temp', 'low');
    } else if (value <= 0.7) {
        element.setAttribute('data-temp', 'medium');
    } else {
        element.setAttribute('data-temp', 'high');
    }
}

/**
 * 初始化按钮事件
 */
function initButtons() {
    const analyzeBtn = document.getElementById('analyze-btn');
    if (analyzeBtn && !analyzeBtn.hasAttribute('data-init')) {
        analyzeBtn.setAttribute('data-init', 'true');
        analyzeBtn.addEventListener('click', startAnalysis);
    }

    const codeInput = document.getElementById('stock-code');
    if (codeInput && !codeInput.hasAttribute('data-init')) {
        codeInput.setAttribute('data-init', 'true');
        codeInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                startAnalysis();
            }
        });
    }
}

/**
 * 主初始化函数
 */
function initIndividualPage() {
    initTemperatureSliders();
    initButtons();
}

// 页面加载后初始化
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initIndividualPage);
} else {
    initIndividualPage();
}

// 窗口加载完成后再次尝试
window.addEventListener('load', () => {
    setTimeout(initIndividualPage, 100);
});
