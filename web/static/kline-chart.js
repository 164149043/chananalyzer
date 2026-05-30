/**
 * K线图渲染模块 - 基于ECharts
 * 支持缠论标记：笔、线段、中枢、买卖点、分型、背离
 */

let klineChart = null;
let _resizeHandler = null;
let _cachedData = null;
let _toggleState = { bi: true, seg: true, zs: true, bsp: true, fractal: true, divergence: true, macd: true };

// ============ 公开接口 ============

async function loadAndRenderKline(stockInput) {
  try {
    const resp = await fetch(`${API_BASE}/stock/${encodeURIComponent(stockInput)}/kline?limit=500`);
    if (!resp.ok) {
      throw new Error(`K线请求失败: HTTP ${resp.status}`);
    }
    const data = await resp.json();
    if (data.error) {
      console.warn('K线数据加载失败:', data.error);
      document.getElementById('klineCard').style.display = 'none';
      return;
    }
    _cachedData = data;
    _toggleState = { bi: true, seg: true, zs: true, bsp: true, fractal: true, divergence: true, macd: true };
    // 重置切换按钮的视觉状态
    document.querySelectorAll('.kline-toggle').forEach(btn => btn.classList.add('active'));
    // 先显示容器，再渲染图表（ECharts 在 display:none 时无法正确计算尺寸）
    document.getElementById('klineCard').style.display = '';
    const dateEl = document.getElementById('klineDataDate');
    if (dateEl && data.data_date) {
      dateEl.textContent = '数据更新至: ' + data.data_date;
    }
    // 加载新股票时销毁旧图表
    destroyKlineChart();
    renderKlineChart(data);
    if (klineChart) klineChart.resize();
    bindToggleButtons();
  } catch (e) {
    console.error('K线请求失败:', e);
    document.getElementById('klineCard').style.display = 'none';
  }
}

function destroyKlineChart() {
  if (_resizeHandler) {
    window.removeEventListener('resize', _resizeHandler);
    _resizeHandler = null;
  }
  if (klineChart) {
    klineChart.dispose();
    klineChart = null;
  }
}

// ============ MACD 计算 ============

function calcEMA(data, period) {
  if (!data.length) return [];
  const result = [];
  const k = 2 / (period + 1);
  result[0] = data[0];
  for (let i = 1; i < data.length; i++) {
    result[i] = data[i] * k + result[i - 1] * (1 - k);
  }
  return result;
}

function calcMACD(closes, fast, slow, signal) {
  const emaFast = calcEMA(closes, fast);
  const emaSlow = calcEMA(closes, slow);
  const dif = emaFast.map((v, i) => v - emaSlow[i]);
  const dea = calcEMA(dif, signal);
  const macd = dif.map((v, i) => (v - dea[i]) * 2);
  return { dif, dea, macd };
}

// ============ 内部实现 ============

function renderKlineChart(data) {
  const dom = document.getElementById('klineChart');
  if (!dom) return;

  const kline = data.kline || [];
  if (!kline.length) return;

  // 复用已有图表实例，避免切换标记时销毁重建
  if (!klineChart) {
    klineChart = echarts.init(dom, null, { renderer: 'canvas' });
    _resizeHandler = () => klineChart && klineChart.resize();
    window.addEventListener('resize', _resizeHandler);
  }

  const dates = kline.map(k => k.date);
  const ohlc = kline.map(k => [k.open, k.close, k.low, k.high]);

  const volumes = kline.map(k => ({
    value: k.volume,
    itemStyle: {
      color: k.close >= k.open ? 'rgba(200,55,46,0.6)' : 'rgba(45,122,92,0.6)'
    }
  }));

  const biLines = buildLineSeriesData(dates, data.bi_list || []);
  const segLines = buildLineSeriesData(dates, data.seg_list || []);

  // MACD 数据
  const closes = kline.map(k => k.close);
  const macdData = calcMACD(closes, 12, 26, 9);

  const showMacd = _toggleState.macd;

  const option = {
    animation: false,
    backgroundColor: '#ffffff',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', crossStyle: { color: '#555' } },
      backgroundColor: 'rgba(20,20,20,0.9)',
      borderColor: '#333',
      textStyle: { color: '#ccc', fontSize: 12 },
      formatter: function (params) {
        if (!params || !params.length) return '';
        let date = params[0].axisValue;
        let html = '<div style="margin-bottom:4px;font-weight:bold;">' + date + '</div>';
        for (const p of params) {
          if (p.seriesType === 'candlestick') {
            const d = p.data;
            html += '<div style="color:#ccc;">开 ' + d[0] + ' 收 ' + d[1] + ' 低 ' + d[2] + ' 高 ' + d[3] + '</div>';
          } else if (p.seriesType === 'bar' && p.seriesName === '成交量') {
            html += '<div style="color:#999;">成交量 ' + (p.value / 10000).toFixed(0) + '万</div>';
          } else if (p.seriesName === 'MACD柱') {
            html += '<div style="color:#999;">MACD ' + p.value.toFixed(3) + '</div>';
          } else if (p.seriesName === 'DIF') {
            html += '<div style="color:#e6a817;">DIF ' + p.value.toFixed(3) + '</div>';
          } else if (p.seriesName === 'DEA') {
            html += '<div style="color:#3b82f6;">DEA ' + p.value.toFixed(3) + '</div>';
          }
        }
        return html;
      }
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: showMacd ? [
      { left: '8%', right: '3%', top: '2%', height: '42%' },
      { left: '8%', right: '3%', top: '50%', height: '10%' },
      { left: '8%', right: '3%', top: '65%', height: '12%' },
    ] : [
      { left: '8%', right: '3%', top: '2%', height: '55%' },
      { left: '8%', right: '3%', top: '63%', height: '14%' },
    ],
    xAxis: showMacd ? [
      {
        type: 'category', data: dates, gridIndex: 0,
        axisLabel: { show: false },
        axisLine: { lineStyle: { color: '#333' } },
        splitLine: { show: false },
      },
      {
        type: 'category', data: dates, gridIndex: 1,
        axisLabel: { show: false },
        axisLine: { lineStyle: { color: '#333' } },
        splitLine: { show: false },
      },
      {
        type: 'category', data: dates, gridIndex: 2,
        axisLabel: { color: '#666', fontSize: 10 },
        axisLine: { lineStyle: { color: '#333' } },
        splitLine: { show: false },
      },
    ] : [
      {
        type: 'category', data: dates, gridIndex: 0,
        axisLabel: { show: false },
        axisLine: { lineStyle: { color: '#333' } },
        splitLine: { show: false },
      },
      {
        type: 'category', data: dates, gridIndex: 1,
        axisLabel: { color: '#666', fontSize: 10 },
        axisLine: { lineStyle: { color: '#333' } },
        splitLine: { show: false },
      },
    ],
    yAxis: showMacd ? [
      {
        type: 'value', gridIndex: 0, scale: true,
        splitLine: { lineStyle: { color: 'rgba(0,0,0,0.06)' } },
        axisLabel: { color: '#888', fontSize: 10 },
      },
      {
        type: 'value', gridIndex: 1, splitNumber: 2,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      {
        type: 'value', gridIndex: 2,
        axisLabel: { color: '#888', fontSize: 9, formatter: v => v.toFixed(2) },
        splitLine: { lineStyle: { color: 'rgba(0,0,0,0.06)' } },
      },
    ] : [
      {
        type: 'value', gridIndex: 0, scale: true,
        splitLine: { lineStyle: { color: 'rgba(0,0,0,0.06)' } },
        axisLabel: { color: '#888', fontSize: 10 },
      },
      {
        type: 'value', gridIndex: 1, splitNumber: 2,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: showMacd ? [0, 1, 2] : [0, 1], start: 70, end: 100 },
      {
        type: 'slider', xAxisIndex: showMacd ? [0, 1, 2] : [0, 1], bottom: '1%', height: 16,
        borderColor: '#333', fillerColor: 'rgba(200,55,46,0.15)',
        handleStyle: { color: '#c8372e' },
        textStyle: { color: '#666', fontSize: 10 },
        dataBackground: {
          lineStyle: { color: '#333' },
          areaStyle: { color: '#f0f0f0' },
        },
      },
    ],
    series: [
      {
        name: 'K线', type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0,
        data: ohlc,
        itemStyle: {
          color: '#c8372e', color0: '#2d7a5c',
          borderColor: '#c8372e', borderColor0: '#2d7a5c',
        },
        markArea: _toggleState.zs ? buildZsMarkArea(data.zs_list || []) : { data: [] },
        markPoint: {
          data: [
            ...(_toggleState.bsp ? buildBsMarkPoint(data.buy_signals || [], data.sell_signals || []).data : []),
            ...(_toggleState.fractal ? buildFractalMarkPoint(data.bi_list || []) : []),
          ],
        },
        markLine: _toggleState.divergence ? buildDivergenceMarkLine(data.bi_list || []) : { data: [] },
      },
      {
        name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
        data: volumes,
      },
      ...(_toggleState.bi ? [
        {
          name: '笔', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
          data: biLines.sureData, connectNulls: true,
          lineStyle: { color: '#e6a817', width: 1.5 },
          symbol: 'none', z: 10,
        },
        {
          name: '笔(待定)', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
          data: biLines.unsureData, connectNulls: true,
          lineStyle: { color: '#e6a817', width: 1.5, type: 'dashed' },
          symbol: 'none', z: 10,
        },
      ] : []),
      ...(_toggleState.seg ? [
        {
          name: '线段', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
          data: segLines.sureData, connectNulls: true,
          lineStyle: { color: '#3b82f6', width: 2.5 },
          symbol: 'none', z: 9,
        },
        {
          name: '线段(待定)', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
          data: segLines.unsureData, connectNulls: true,
          lineStyle: { color: '#3b82f6', width: 2.5, type: 'dashed' },
          symbol: 'none', z: 9,
        },
      ] : []),
      // MACD 副图
      ...(showMacd ? [
        {
          name: 'MACD柱', type: 'bar', xAxisIndex: 2, yAxisIndex: 2,
          data: macdData.macd.map(v => ({
            value: v,
            itemStyle: { color: v >= 0 ? 'rgba(200,55,46,0.6)' : 'rgba(45,122,92,0.6)' },
          })),
        },
        {
          name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2,
          data: macdData.dif,
          lineStyle: { color: '#e6a817', width: 1 },
          symbol: 'none',
        },
        {
          name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2,
          data: macdData.dea,
          lineStyle: { color: '#3b82f6', width: 1 },
          symbol: 'none',
        },
      ] : []),
    ],
  };

  klineChart.setOption(option, true);
}

// ============ 笔/线段数据构建 ============

function buildLineSeriesData(klineDates, items) {
  const dateIdx = {};
  klineDates.forEach((d, i) => dateIdx[d] = i);

  const sureData = new Array(klineDates.length).fill(null);
  const unsureData = new Array(klineDates.length).fill(null);

  for (const item of items) {
    const si = dateIdx[item.start_date];
    const ei = dateIdx[item.end_date];

    const target = item.is_sure ? sureData : unsureData;
    const other = item.is_sure ? unsureData : sureData;

    if (si !== undefined) {
      target[si] = item.start_price;
      if (other[si] === null) other[si] = item.start_price;
    }
    if (ei !== undefined) {
      target[ei] = item.end_price;
      if (other[ei] === null) other[ei] = item.end_price;
    }
  }

  return { sureData, unsureData };
}

// ============ 中枢 markArea ============

function buildZsMarkArea(zsList) {
  if (!zsList.length) return { data: [] };
  return {
    data: zsList.map(zs => [
      { xAxis: zs.start_date, yAxis: zs.low, name: 'ZS' + zs.idx },
      { xAxis: zs.end_date, yAxis: zs.high },
    ]),
    itemStyle: {
      color: 'rgba(255,140,0,0.06)',
      borderColor: 'rgba(255,140,0,0.5)',
      borderWidth: 1,
    },
    label: {
      show: true, position: 'insideTop',
      formatter: function (p) { return p.name || ''; },
      color: 'rgba(255,140,0,0.7)', fontSize: 10,
    },
  };
}

// ============ 买卖点 markPoint ============

function buildBsMarkPoint(buySignals, sellSignals) {
  const points = [];

  for (const s of buySignals) {
    points.push({
      name: s.type + '买', coord: [s.date, s.price],
      symbol: 'triangle', symbolSize: 10, symbolRotate: 0, symbolOffset: [0, '-55%'],
      itemStyle: { color: '#c8372e' },
      label: { show: true, position: 'bottom', formatter: '{b}', color: '#c8372e', fontSize: 12 },
    });
  }
  for (const s of sellSignals) {
    points.push({
      name: s.type + '卖', coord: [s.date, s.price],
      symbol: 'triangle', symbolSize: 10, symbolRotate: 180, symbolOffset: [0, '55%'],
      itemStyle: { color: '#2d7a5c' },
      label: { show: true, position: 'top', formatter: '{b}', color: '#2d7a5c', fontSize: 12 },
    });
  }

  return { data: points, animation: false };
}

// ============ 分型标记 ============

function buildFractalMarkPoint(biList) {
  const points = [];
  if (!biList.length) return points;

  const firstBi = biList[0];
  if (firstBi.dir === '向上') {
    points.push({
      name: '底分型', coord: [firstBi.start_date, firstBi.start_price],
      symbol: 'diamond', symbolSize: 8,
      itemStyle: { color: '#c8372e' },
      label: { show: false },
    });
  } else if (firstBi.dir === '向下') {
    points.push({
      name: '顶分型', coord: [firstBi.start_date, firstBi.start_price],
      symbol: 'diamond', symbolSize: 8,
      itemStyle: { color: '#2d7a5c' },
      label: { show: false },
    });
  }

  for (let i = 0; i < biList.length; i++) {
    const bi = biList[i];
    // 向上笔的终点 = 顶分型
    if (bi.dir === '向上') {
      points.push({
        name: '顶分型', coord: [bi.end_date, bi.end_price],
        symbol: 'diamond', symbolSize: 8,
        itemStyle: { color: '#2d7a5c' },
        label: { show: false },
      });
    }
    // 向下笔的终点 = 底分型
    if (bi.dir === '向下') {
      points.push({
        name: '底分型', coord: [bi.end_date, bi.end_price],
        symbol: 'diamond', symbolSize: 8,
        itemStyle: { color: '#c8372e' },
        label: { show: false },
      });
    }
  }

  return points;
}

// ============ 背离检测 ============

function buildDivergenceMarkLine(biList) {
  const lines = [];
  if (!biList.length) return { data: [] };

  // 收集向上笔的终点（顶点）和向下笔的终点（底点）
  const tops = [];
  const bottoms = [];

  for (const bi of biList) {
    const point = { date: bi.end_date, price: bi.end_price, macd: bi.macd };
    if (bi.dir === '向上') {
      tops.push(point);
    } else if (bi.dir === '向下') {
      bottoms.push(point);
    }
  }

  // 顶背离：连续两个顶点，后一个价格更高但 MACD 更低
  for (let i = 1; i < tops.length; i++) {
    const prev = tops[i - 1];
    const curr = tops[i];
    if (curr.price > prev.price &&
        prev.macd != null && curr.macd != null &&
        curr.macd < prev.macd) {
      lines.push([
        { coord: [prev.date, prev.price] },
        { coord: [curr.date, curr.price], name: '顶背离' },
      ]);
    }
  }

  // 底背离：连续两个底点，后一个价格更低但 MACD 更高
  for (let i = 1; i < bottoms.length; i++) {
    const prev = bottoms[i - 1];
    const curr = bottoms[i];
    if (curr.price < prev.price &&
        prev.macd != null && curr.macd != null &&
        curr.macd > prev.macd) {
      lines.push([
        { coord: [prev.date, prev.price] },
        { coord: [curr.date, curr.price], name: '底背离' },
      ]);
    }
  }

  if (!lines.length) return { data: [] };

  return {
    data: lines,
    symbol: 'none',
    lineStyle: { width: 1.5, type: 'dashed' },
    label: {
      show: true, position: 'middle',
      formatter: '{b}',
      fontSize: 11, fontWeight: 'bold',
    },
  };
}

// ============ 切换按钮 ============

let _toggleBound = false;
function bindToggleButtons() {
  if (_toggleBound) return;
  _toggleBound = true;

  // 重置按钮视觉状态
  document.querySelectorAll('.kline-toggle').forEach(btn => {
    btn.classList.add('active');
    btn.addEventListener('click', function () {
      if (!klineChart || !_cachedData) return;
      const type = this.dataset.toggle;
      const isActive = this.classList.toggle('active');
      _toggleState[type] = isActive;

      // 所有标记类型统一通过重新渲染切换
      renderKlineChart(_cachedData);
    });
  });
}
