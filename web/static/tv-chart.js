/**
 * TradingView 图表模块(chananalyzer 版) — 移植自 chanlun-pro charts.js 并适配
 *
 * 依赖(由 loadTvChartAssets() 懒加载):
 *   /static/datafeeds/udf/dist/bundle.js   魔改版 datafeed(缠论数据经 bars_result 透传)
 *   /static/charting_library/              TradingView 图表库(商业授权,不进 git)
 *
 * 协议: 后端 /tv/*(web/tv.py, cookie 认证)。
 *   缠论字段 fxs/bis/xds/bi_zss/bcs/mmds 随 /tv/history 响应返回,
 *   datafeed 魔改版将其合并进 bars_result 缓存,本模块订阅事件后取出绘制。
 *
 * 相对 chanlun-pro 原版的裁剪:
 *   - 移除 layui/jQuery 依赖(删除标记按钮)、AI预测、自选股、自定义 Pine 指标
 *   - Utils.* 换成本模块内 localStorage 封装
 *   - 图表布局走 TV localStorage(后端无 /tv/charts 存储端点)
 *
 * 用法: TVChart.open('000001')   // 打开/切换股票
 */
(function () {
  "use strict";

  var LS_KEY_INTERVAL = "tv_interval";
  var LS_KEY_THEME = "tv_theme";

  var CHART_CONFIG = {
    COLORS: {
      DING: "#FA8072",
      DI: "#1E90FF",
      BI: "#708090",
      XD: "#00BFFF",
      ZSD: "#FFA710",
      BI_ZSS: "#708090",
      XD_ZSS: "#00BFFF",
      ZSD_ZSS: "#FFA710",
      BCS: "#D1D4DC",
      BC_TEXT: "#fccbcd",
      MMD_UP: "#FA8072",
      MMD_DOWN: "#1E90FF",
    },
    LINE_STYLES: { SOLID: 0, DOTTED: 1, DASHED: 2 },
    CHART_TYPES: ["fxs", "bis", "xds", "zsds", "bi_zss", "xd_zss", "zsd_zss", "bcs", "mmds"],
  };

  function debounce(func, wait) {
    var timeout;
    return function () {
      var args = arguments, self = this;
      clearTimeout(timeout);
      timeout = setTimeout(function () { func.apply(self, args); }, wait);
    };
  }

  var ChartUtils = {
    createShape: function (chart, points, options) {
      options = options || {};
      var config = Object.assign(
        {
          lock: true,
          disableSelection: true,
          disableSave: true,
          disableUndo: true,
          showInObjectsTree: false,
          overrides: {},
        },
        options
      );
      return config.shape === "trend_line" || config.shape === "rectangle" || config.shape === "circle"
        ? chart.createMultipointShape(points, config)
        : chart.createShape(points, config);
    },

    createFxShape: function (chart, fx, options) {
      options = options || {};
      var color = fx.text === "ding" ? CHART_CONFIG.COLORS.DING : CHART_CONFIG.COLORS.DI;
      return this.createShape(chart, fx.points, {
        shape: "circle",
        overrides: Object.assign(
          { backgroundColor: color, color: color, linewidth: 4 },
          options.overrides || {}
        ),
      });
    },

    createLineShape: function (chart, line, options) {
      options = options || {};
      var extra = options.overrides || {};
      var ls = parseInt(line.linestyle, 10);
      ls = ls === 1 || ls === 2 ? ls : 0;
      var merged = Object.assign(
        {
          linestyle: ls,
          linewidth: options.linewidth || 1,
          linecolor: options.color || CHART_CONFIG.COLORS.BI,
        },
        extra
      );
      var rest = Object.assign({}, options);
      delete rest.overrides;
      delete rest.linewidth;
      delete rest.color;
      return this.createShape(chart, line.points, Object.assign(rest, {
        shape: "trend_line",
        overrides: merged,
      }));
    },

    createZhongshuShape: function (chart, zs, options) {
      options = options || {};
      var color = options.color || CHART_CONFIG.COLORS.BI;
      var rest = Object.assign({}, options);
      delete rest.overrides;
      delete rest.linewidth;
      delete rest.color;
      return this.createShape(chart, zs.points, Object.assign(rest, {
        shape: "rectangle",
        overrides: Object.assign(
          {
            linestyle: parseInt(zs.linestyle, 10) || 0,
            linewidth: 1,
            linecolor: color,
            backgroundColor: color,
            transparency: 95,
            color: color,
            "trendline.linecolor": color,
            fillBackground: true,
            filled: true,
          },
          options.overrides || {}
        ),
      }));
    },

    createMmdShape: function (chart, mmd, options) {
      options = options || {};
      var isBuy = String(mmd.text).indexOf("B") !== -1;
      var color = isBuy ? CHART_CONFIG.COLORS.MMD_UP : CHART_CONFIG.COLORS.MMD_DOWN;
      return this.createShape(chart, mmd.points, {
        shape: isBuy ? "arrow_up" : "arrow_down",
        text: mmd.text,
        overrides: Object.assign(
          { markerColor: color, backgroundColor: color, color: color, fontsize: 12, transparency: 80 },
          options.overrides || {}
        ),
      });
    },

    createBcShape: function (chart, bc, options) {
      options = options || {};
      return this.createShape(chart, bc.points, {
        shape: "balloon",
        text: bc.text,
        overrides: Object.assign(
          {
            markerColor: CHART_CONFIG.COLORS.BCS,
            backgroundColor: CHART_CONFIG.COLORS.BCS,
            textColor: CHART_CONFIG.COLORS.BC_TEXT,
            transparency: 70,
            backgroundTransparency: 70,
            fontsize: 12,
          },
          options.overrides || {}
        ),
      });
    },
  };

  function ChartManager(containerId) {
    this.id = containerId;
    this.obj_charts = {};
    this.widget = null;
    this.udf_datafeed = null;
    this.chart = null;
    this.currentCode = null;
    this.debouncedDrawChanlun = debounce(this.draw_chanlun.bind(this), 1000);
    this._drawRetryTimer = null;
    this._drawRetryCount = 0;
  }

  ChartManager.prototype.init = function (code) {
    this.currentCode = code;
    var interval = localStorage.getItem(LS_KEY_INTERVAL) || "1D";
    var theme = localStorage.getItem(LS_KEY_THEME) || "dark";

    this.udf_datafeed = new Datafeeds.UDFCompatibleDatafeed("/tv", 30000);
    this.widget = new TradingView.widget({
      debug: false,
      autosize: true,
      fullscreen: false,
      // 此库版本用 container(选择器字符串); container_id 为新版 API,此版本不识别
      container: this.id,
      symbol: "a:" + code,
      interval: interval,
      datafeed: this.udf_datafeed,
      library_path: "/static/charting_library/",
      locale: "zh",
      timezone: "Asia/Shanghai",
      theme: theme,
      numeric_formatting: { decimal_sign: "." },
      time_frames: [],
      symbol_search_request_delay: 100,
      auto_save_delay: 5,
      study_count_limit: 100,
      disabled_features: ["go_to_date"],
      enabled_features: ["seconds_resolution"],
    });

    this.setupEventListeners();
    return this;
  };

  ChartManager.prototype.setupEventListeners = function () {
    var manager = this;
    var widget = this.widget;

    widget.onChartReady(function () {
      manager.chart = widget.activeChart();

      manager.chart.onSymbolChanged().subscribe(null, function (symbol) {
        manager.handleSymbolChange(symbol);
      });
      manager.chart.onIntervalChanged().subscribe(null, function (interval) {
        manager.handleIntervalChange(interval);
      });
      manager.chart.onDataLoaded().subscribe(null, function () {
        manager.handleDataLoaded();
      });
      manager.widget.activeChart && widget.activeChart().onVisibleRangeChanged().subscribe(null, function () {
        manager.handleVisibleRangeChange();
      });

      // 工具栏按钮: 重新加载数据
      widget.headerReady().then(function () {
        var btnReload = widget.createButton();
        btnReload.textContent = "刷新数据";
        btnReload.addEventListener("click", function () {
          widget.resetCache();
          widget.activeChart().resetData();
        });
      });
    });
  };

  ChartManager.prototype.resetDrawRetry = function () {
    this._drawRetryCount = 0;
    if (this._drawRetryTimer) {
      clearTimeout(this._drawRetryTimer);
      this._drawRetryTimer = null;
    }
  };

  ChartManager.prototype.handleSymbolChange = function (symbol) {
    if (!symbol || !symbol.ticker) return;
    var parts = String(symbol.ticker).split(":");
    if (parts.length === 2) this.currentCode = parts[1];
    this.resetDrawRetry();
    this.clear_draw_chanlun();
    this.debouncedDrawChanlun();
  };

  ChartManager.prototype.handleIntervalChange = function (interval) {
    if (!interval) return;
    localStorage.setItem(LS_KEY_INTERVAL, interval);
    this.resetDrawRetry();
    this.clear_draw_chanlun();
    this.debouncedDrawChanlun();
  };

  ChartManager.prototype.handleDataLoaded = function () {
    this.clear_draw_chanlun();
    this.debouncedDrawChanlun();
  };

  ChartManager.prototype.handleVisibleRangeChange = function () {
    this.debouncedDrawChanlun();
  };

  ChartManager.prototype.removeEntityIfExist = function (idPromise) {
    var chart = this.chart;
    return idPromise
      .then(function (_id) {
        try {
          var exists = chart.getAllShapes().some(function (s) { return s.id === _id; });
          if (exists) chart.removeEntity(_id);
        } catch (e) { /* 图表已重置等情况 */ }
      })
      .catch(function () {});
  };

  ChartManager.prototype.clear_draw_chanlun = function () {
    var manager = this;
    Object.keys(this.obj_charts).forEach(function (symbolKey) {
      var chartContainer = manager.obj_charts[symbolKey];
      CHART_CONFIG.CHART_TYPES.forEach(function (type) {
        (chartContainer[type] || []).forEach(function (item) {
          if (item.id && item.id.then) manager.removeEntityIfExist(item.id);
        });
        chartContainer[type] = [];
      });
    });
  };

  ChartManager.prototype.getChartData = function () {
    if (!this.widget || !this.chart) return null;
    var si = this.widget.symbolInterval();
    if (!si) return null;

    var symbolResKey = String(si.symbol).toLowerCase() + String(si.interval).toLowerCase();
    var barsResult =
      this.udf_datafeed && this.udf_datafeed._historyProvider
        ? this.udf_datafeed._historyProvider.bars_result.get(symbolResKey)
        : null;
    if (!barsResult) return null;

    var visibleRange = this.chart.getVisibleRange();
    var from = (visibleRange && visibleRange.from) || 0;
    var symbolKey = si.symbol + "_" + si.interval;
    return { symbolKey: symbolKey, barsResult: barsResult, from: from };
  };

  ChartManager.prototype.initChartContainer = function (symbolKey) {
    if (!this.obj_charts[symbolKey]) {
      this.obj_charts[symbolKey] = {};
      var c = this.obj_charts[symbolKey];
      CHART_CONFIG.CHART_TYPES.forEach(function (t) { c[t] = []; });
    }
    return this.obj_charts[symbolKey];
  };

  ChartManager.prototype.draw_chanlun = function () {
    var chartData = this.getChartData();
    if (!chartData) {
      // 数据未就绪(周期切换后端计算可能超过防抖时间): 限次重试
      if (this._drawRetryCount < 8) {
        this._drawRetryCount++;
        var manager = this;
        this._drawRetryTimer = setTimeout(function () { manager.draw_chanlun(); }, 1000);
      }
      return;
    }
    this._drawRetryCount = 0;

    var symbolKey = chartData.symbolKey;
    var barsResult = chartData.barsResult;
    var from = chartData.from;

    this.clear_draw_chanlun();
    var cc = this.initChartContainer(symbolKey);
    var chart = this.chart;
    var self = this;

    function drawList(type, drawFn) {
      var list = barsResult[type];
      if (!list) return;
      list.forEach(function (item) {
        if (!item || !item.points) return;
        // 线类/中枢/分型的 points 是数组;买卖点(mmds)/背驰(bcs)的 points 是单对象
        var pt = Array.isArray(item.points) ? item.points[0] : item.points;
        if (pt && pt.time >= from) {
          var key = JSON.stringify(item);
          var existed = cc[type].some(function (x) { return x.key === key; });
          if (existed) return;
          cc[type].push({ time: pt.time, key: key, id: drawFn(chart, item) });
        }
      });
    }

    drawList("fxs", function (c, it) { return ChartUtils.createFxShape(c, it); });
    drawList("bis", function (c, it) {
      return ChartUtils.createLineShape(c, it, { color: CHART_CONFIG.COLORS.BI, linewidth: 1 });
    });
    drawList("xds", function (c, it) {
      return ChartUtils.createLineShape(c, it, { color: CHART_CONFIG.COLORS.XD, linewidth: 2 });
    });
    drawList("zsds", function (c, it) {
      return ChartUtils.createLineShape(c, it, { color: CHART_CONFIG.COLORS.ZSD, linewidth: 3 });
    });
    drawList("bi_zss", function (c, it) {
      return ChartUtils.createZhongshuShape(c, it, { color: CHART_CONFIG.COLORS.BI_ZSS });
    });
    drawList("xd_zss", function (c, it) {
      return ChartUtils.createZhongshuShape(c, it, { color: CHART_CONFIG.COLORS.XD_ZSS });
    });
    drawList("zsd_zss", function (c, it) {
      return ChartUtils.createZhongshuShape(c, it, { color: CHART_CONFIG.COLORS.ZSD_ZSS });
    });
    drawList("bcs", function (c, it) { return ChartUtils.createBcShape(c, it); });
    drawList("mmds", function (c, it) { return ChartUtils.createMmdShape(c, it); });
  };

  ChartManager.prototype.setSymbol = function (code) {
    this.currentCode = code;
    this.resetDrawRetry();
    this.clear_draw_chanlun();
    if (this.widget) {
      this.widget.setSymbol("a:" + code, localStorage.getItem(LS_KEY_INTERVAL) || "1D");
    }
  };

  // ==================== 对外接口 ====================

  var manager = null;

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("加载失败: " + src)); };
      document.head.appendChild(s);
    });
  }

  /**
   * 打开 TV 图表(懒加载资产; 已打开则切换标的)
   * @param code 股票代码,如 '000001'
   */
  function open(code) {
    var el = document.getElementById("tv_chart_container");
    if (!el) return;
    if (!window.Datafeeds || !window.TradingView) {
      loadScript("/static/datafeeds/udf/dist/bundle.js")
        .then(function () { return loadScript("/static/charting_library/charting_library.standalone.js"); })
        .then(function () {
          if (!manager) manager = new ChartManager("tv_chart_container").init(code);
          else manager.setSymbol(code);
        })
        .catch(function (e) {
          el.innerHTML = '<div style="padding:40px;color:#e74c3c;text-align:center">图表资源加载失败: ' +
            e.message + '<br>请确认 web/static/charting_library 已放置</div>';
        });
      return;
    }
    if (!manager) manager = new ChartManager("tv_chart_container").init(code);
    else manager.setSymbol(code);
  }

  window.TVChart = { open: open };
})();
