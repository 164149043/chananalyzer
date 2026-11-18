# ChanAnalyzer - 缠论分析系统（A股 + 数字货币）

> 本项目基于 [Vespa314/chan.py](https://github.com/Vespa314/chan.py) 进行二次开发

**原项目链接**: https://github.com/Vespa314/chan.py | **本项目仓库**: https://github.com/164149043/chananalyzer

---

## 二次开发内容

基于原始 chan.py 项目，本版本进行了以下增强和改进：

- 🤖 **AI 智能分析模块** - 双分析师 + 决策者多 AI 协作，SSE 流式输出，Markdown 渲染
- 📊 **TradingView 专业图表** - 官方 charting_library，K线叠加缠论标注（笔/线段/中枢/买卖点），布局云同步
- 📡 **多市场多数据源** - A股（通达信，精确前复权）+ 数字货币（Binance 公开行情镜像），分钟到周线八档周期
- 🌐 **FastAPI Web 平台** - 多用户认证（注册审核制）、邮箱验证码、AI 每日限额
- ⚡ **按需缓存** - SQLite 全量K线缓存 + 分钟线按需拉取 + 7×24 币数据兜底刷新
- 🔍 **批量扫描** - 全市场买卖点信号扫描、行业/地区筛选、资金流向排序

---

基于缠论（缠中说禅）技术分析的行情分析工具，支持笔、线段、中枢、买卖点自动识别，覆盖 **A股与主流数字货币现货**，周期从 1 分钟到周线。

## 特性

- **缠论核心分析**：自动识别笔、线段、中枢结构，一/二/三类买卖点检测
- **多周期分析**：1M / 5M / 15M / 30M / 60M / 4H / 日线 / 周线（A股暂日线/周线+分钟图表）
- **TradingView 图表**：官方图表库，K线叠加缠论标注，支持布局保存与云同步
- **双市场支持**：A股（通达信数据源，精确前复权）+ 数字货币（Binance 镜像，7×24）
- **AI 智能分析**：双分析师不同温度并行分析 + 决策者完全分类范式综合判断
- **多用户系统**：JWT 认证、注册审核制、邮箱验证码、AI 每日限额、管理员后台
- **本地缓存**：SQLite 本地缓存，离线快速分析
- **批量扫描**：一键扫描全市场买卖点信号

## 快速开始

### 1. 配置环境

```bash
# 复制配置模板并填入你的实际值
cp .env.example .env
```

必需配置（详见 `.env.example` 注释）：

| 变量 | 用途 |
|------|------|
| `TUSHARE_TOKEN` | 股票信息/资金流向等数据 |
| `SILICONFLOW_API_KEY` 或 `DEEPSEEK_API_KEY` | AI 智能分析 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理员账号（首次启动自动创建） |

### 2. 启动 Web 服务

```bash
python web/start_server.py

# 或直接启动
python -m uvicorn web.api:app --host 0.0.0.0 --port 8899
```

然后访问：**http://localhost:8899**

Web 功能包括：
- 📊 **仪表盘** - 市场概况、买卖点统计、热门板块
- 📈 **个股分析** - 代码/名称/币简名输入，TV图表 + 多 AI 协作分析
- ⚡ **买点扫描** - 一买、一买衍生、二买、三买 A/B 批量扫描
- 💰 **卖点扫描** - 一卖、二卖、三卖 A/B 批量扫描
- 🔥 **热门扫描** - 涨幅/跌幅/成交额/成交量/换手率/龙虎榜

### 3. 首次缓存数据

```bash
# 同步股票基本信息（名称、行业、地区）
python -m scripts.cache_stock_info

# 批量缓存日线（通达信数据源，免费无频次限制）
python -m scripts.update_data --all
```

---

## 数字货币模块

支持 BTC、ETH 等主流币现货的缠论分析与 AI 分析，默认数据源为 **Binance 公开行情镜像**（`data-api.binance.vision`，免 API key，大陆网络可直连）。

### 数据特性

- **按需缓存**：首次请求某币某周期才拉取入缓存（八档周期，单周期约 1000 根）
- **7×24 兜底刷新**：进行中 bar 每 10 分钟更新快照，走完的 bar 按周期冷却等待新 bar
- **时间口径**：日/周线统一北京日期 00:00，分钟线存 bar 开始时刻
- **白名单**：默认内置前 20 主流币，可通过 `.env` 的 `BINANCE_SYMBOLS` 自定义

### 配置项（.env）

```bash
# K线数据源: binance(默认,公开镜像直连) / okx(需代理,见 OKX_PROXY)
# CRYPTO_SOURCE=binance

# 币白名单(逗号分隔;不配置则用内置前20主流)
# BINANCE_SYMBOLS=BTC-USDT,ETH-USDT,SOL-USDT

# 币功能总开关: 1=对所有用户开放;留空/0=仅管理员可用(默认,保守)
# ENABLE_CRYPTO=1
```

### 使用方式

- **TV 图表**：个股分析页输入 `btc` / `BTC-USDT` 直达，支持八档周期切换与缠论标注
- **AI 分析**：选择周期（1分钟~周线八档）后分析，分析师与决策者使用币版提示词（7×24、无涨跌停、爆仓级波动风险等市场特性）

---

## 命令行使用

### 扫描器选择

系统提供两种扫描器，可根据需求选择：

| 扫描器 | 数据源 | 速度 | 功能 | 适用场景 |
|--------|--------|------|------|----------|
| `scan_stocks_cache.py` | 本地数据库 | **快** | 买卖点+行业/地区+资金流向 | **推荐日常使用** |
| `scan_stocks.py` | Tushare API | 慢 | 全功能 | 需要实时数据 |

### 本地缓存扫描器（推荐）

使用本地 `chan.db` 进行 K 线分析，速度快无需联网（可选获取行业/资金流向）。

```bash
# 扫描所有股票（从本地数据库）
python scan_stocks_cache.py

# 扫描指定股票
python scan_stocks_cache.py --codes 000001 000002 600000

# 按行业筛选
python scan_stocks_cache.py --industry 电子 计算机

# 筛选特定买点
python scan_stocks_cache.py --buy 1 2 3a

# 组合使用：电子行业 + 二买三买 + 主力流入
python scan_stocks_cache.py --industry 电子 --buy 2 3a 3b --min-money-flow 500 --sort-by-money-flow
```

### 分析单只股票

```bash
python -c "
from ChanAnalyzer import ChanAnalyzer
analyzer = ChanAnalyzer(code='000001')
print(analyzer.get_summary())
"
```

### AI 智能分析

```bash
# 单 AI 分析
python -m scripts.ai_analyze --code 000001

# 多 AI 协作分析（推荐）
python -m scripts.multi_ai_analyze --code 000001
```

**多 AI 分析流程**：
```
缠论数据 + 资金流向 + 盘中实时行情
    → [分析师A + 分析师B] 并行分析 → 决策者综合 → 最终建议
```

**配置文件** (`ai_config.yaml`，修改后无需重启服务)：

```yaml
# AI服务提供商(支持 deepseek / siliconflow)
provider:
  name: siliconflow
  api_key_env: SILICONFLOW_API_KEY
  base_url: https://api.siliconflow.cn/v1

# 分析师配置(双分析师不同温度获得多样化观点)
analysts:
  count: 2
  models:
    - deepseek-ai/DeepSeek-V4-Flash   # 分析师A
    - deepseek-ai/DeepSeek-V4.1-Flash # 分析师B
  temperatures: [0.3, 0.6]
  max_tokens: 1500

# 决策者配置
decision_maker:
  model: deepseek-ai/DeepSeek-V4-Pro
  temperature: 0.3
  # 推理模型思维链优先消耗额度,必须给足,否则正文可能为空
  max_tokens: 8000
```

---

## Web 界面

### 功能模块

| 模块 | 功能 | 说明 |
|------|------|------|
| 📊 仪表盘 | 市场概览 | 指数概览、买卖点统计、热门板块、买点推荐 |
| 📈 个股分析 | TV图表 + AI 分析 | 双分析师 + 决策者，SSE 流式输出 Markdown 渲染；A股/币通用入口 |
| ⚡ 买点扫描 | 批量扫描 | 一买、一买衍生、二买、三买 A/B |
| 💰 卖点扫描 | 批量扫描 | 一卖、二卖、三卖 A/B |
| 🔥 热门扫描 | 热门股票扫描 | 涨幅/跌幅/成交额/成交量/换手率/龙虎榜排名 |
| 📚 缠论说明 | 理论学习 | 缠论核心概念、买卖点类型、操作原则 |

### TV 图表

个股分析页基于 TradingView 官方 `charting_library`，K线直接叠加缠论标注：

| 标注 | 说明 |
|------|------|
| 笔 | 黄色实线/虚线（确认/待定） |
| 线段 | 蓝色粗线 |
| 中枢 | 橙色半透明区间 + 编号 |
| 买卖点 | 红色三角(买)/绿色倒三角(卖) |

- **周期**：A股 5分钟~周线（分钟线按需缓存+盘中兜底刷新），币 1分钟~周线八档
- **布局云同步**：画图/指标布局保存到账号，多端一致
- **刷新数据**：币图表按钮触发后端绕冷却强制增量刷新（更新进行中 bar 快照）

### 用户系统

- **注册审核制**：邮箱验证码注册 → 管理员审核激活（pending → active）
- **会话**：JWT 有效期默认 7 天，前端每 12 小时自动续期，页面长开不掉线
- **AI 限额**：普通用户每日 5 次 AI 分析（`AI_DAILY_LIMIT` 可调），管理员不限
- **权限**：币功能默认仅管理员可见（`ENABLE_CRYPTO=1` 对所有用户开放）

### Web API 端点（节选）

```bash
# 认证
POST /api/auth/login          # 登录
POST /api/auth/send-code      # 发送邮箱验证码
POST /api/auth/register       # 注册(审核制)
POST /api/auth/refresh        # 刷新 token
GET  /api/auth/me             # 当前用户信息

# 分析与扫描
POST /api/stock/analyze       # AI 分析（SSE 流式,A股/币通用,币可选周期）
GET  /api/stock/resolve       # 代码/名称/币简名解析
POST /api/scan/buy/start      # 启动买点扫描
GET  /api/scan/buy/results    # 获取扫描结果

# TV 图表 datafeed（UDF 协议,cookie 认证）
GET  /tv/config               # 图表配置(含交易所列表)
GET  /tv/symbols              # 标的元信息
GET  /tv/search               # 标的搜索(A股+白名单币)
GET  /tv/history              # K线历史(含缠论标注扩展字段)
GET  /tv/refresh              # 强制刷新币当前周期缓存
```

完整清单启动服务后访问 **http://localhost:8899/docs**。

---

## 数据源与缓存

### 数据源

| 市场 | K线数据源 | 说明 |
|------|-----------|------|
| A股 | 通达信行情服务器（内置 vendor/pytdx） | 免费无频次限制，精确前复权（含特殊除权自愈），日线/分钟线 |
| A股 | Tushare Pro | 股票基本信息（名称/行业/地区）、资金流向、热门榜单等辅助数据 |
| 数字货币 | Binance 公开行情镜像 | 免 key 直连；可切 OKX 源（`CRYPTO_SOURCE=okx`，需代理） |

### 缓存策略

- **存储位置**: `./chan.db`（SQLite，K线数据统一表，market 列区分市场）
- **A股日线**: `update_data.py` 批量缓存/每日增量更新
- **A股分钟线**: 用户首次请求才拉取，盘中自动兜底刷新
- **币全周期**: 按需缓存 + 7×24 兜底刷新，白名单限制入库标的

### Tushare 权限参考（信息类数据）

| 权限等级 | 每分钟频次 | 每日总量 | 适用场景 |
|----------|------------|----------|----------|
| 免费账户 | 200 次 | 10,000 次 | 测试、个人使用 |
| 普通用户 | 500 次 | 100,000 次 | **推荐** |

---

## 项目结构

```
chananalyzer/
├── ChanAnalyzer/           # 分析模块
│   ├── analyzer.py         # 核心分析器（缠论引擎封装）
│   ├── multi_ai_analyzer.py # 多AI协作分析器
│   ├── database.py         # 数据库模型（KLineData,多市场）
│   ├── tdx_source.py       # 通达信K线数据源(精确前复权)
│   ├── binance_source.py   # Binance镜像K线数据源(默认币源)
│   ├── okx_source.py       # OKX K线数据源(备用币源,需代理)
│   ├── binance_cache.py    # 币K线按需缓存+7x24兜底刷新+开关
│   ├── realtime_quote.py   # 盘中实时行情
│   ├── sector_flow.py      # 个股/板块资金流向
│   ├── prompts/            # AI提示词模板(A股/币双市场)
│   └── formatter.py        # 格式化输出
├── Common/  KLine/  Bi/  Seg/  Zs/   # CChan 引擎(内置)
├── vendor/pytdx/           # pytdx 修复版(通达信协议)
├── web/                    # Web界面
│   ├── api.py             # FastAPI 后端(扫描/分析/认证)
│   ├── auth.py            # JWT认证/注册审核/限额
│   ├── tv.py              # TV图表UDF datafeed+布局云同步
│   ├── mail.py / captcha.py / security.py
│   └── static/            # 前端(原生HTML/JS/CSS,无构建)
│       ├── index.html     # 单页应用
│       └── tv-chart.js    # TV图表模块(缠论标注绘制)
├── scripts/                # 脚本工具
│   ├── update_data.py     # K线数据增量更新
│   ├── cache_stock_info.py # 股票基本信息同步
│   ├── multi_ai_analyze.py # 多AI协作分析脚本
│   └── reseed_tdx.py      # tdx数据重播种
├── scan_stocks_cache.py   # 本地缓存扫描器(推荐)
├── ai_config.yaml         # AI配置(改模型无需重启)
├── .env.example           # 环境变量模板
└── chan.db                # 本地K线缓存数据库
```

---

## 买卖点类型

| 类型 | 代码 | 说明 | 方向 |
|------|------|------|------|
| 一买 | `1`, `1p` | 第一类买点及衍生 | 买入 |
| 二买 | `2` | 第二类买点 | 买入 |
| 三买A | `3a` | 第三类买点A型 | 买入 |
| 三买B | `3b` | 第三类买点B型 | 买入 |
| 二卖 | `2s` | 类二卖点 | 卖出 |

> 卖点：一卖(`1`)、二卖(`2`)、三卖A(`3a`)、三卖B(`3b`) 均已支持。

---

## 常见问题

### Q: 首次使用应该执行哪些命令？

```bash
# 1. 配置 .env(复制 .env.example 填入 token/key/管理员账号)
cp .env.example .env

# 2. 同步股票基本信息
python -m scripts.cache_stock_info

# 3. 批量缓存日线
python -m scripts.update_data --all

# 4. 启动服务
python web/start_server.py
```

### Q: 币功能看不到？

**A**: 默认仅管理员可见。`.env` 配置 `ENABLE_CRYPTO=1` 对所有用户开放（改完重启服务）。

### Q: 币的数据从哪里来？需要翻墙吗？

**A**: 默认走 Binance 公开行情镜像（data-api.binance.vision），大陆网络可直连，无需代理与 API key。如需切 OKX 源，`.env` 配 `CRYPTO_SOURCE=okx` 并配置 `OKX_PROXY`。

### Q: 如何更新所有股票数据？

```bash
python -m scripts.update_data --all
```

### Q: 扫描结果为什么是 0？

**A**: 可能原因：
1. 未缓存 K 线数据 - 先运行 `python -m scripts.update_data --all`
2. 筛选条件过于严格 - 尝试减少选择的买卖点类型
3. 数据库路径问题 - 确保 `chan.db` 在项目根目录

### Q: AI 分析报错 / 输出为空？

**A**:
1. 检查 `.env` 的 API Key 是否有效
2. 决策者输出为空多为 `max_tokens` 不足——推理模型（R1/Step 系列）思维链优先消耗额度，需给足（当前配置 8000）
3. 模型 403 `Model disabled` 为服务商下架该模型，换 `ai_config.yaml` 中的模型名即可（无需重启）

### Q: 局域网如何访问？

```bash
python -m uvicorn web.api:app --host 0.0.0.0 --port 8899
```

---

## 依赖项

### 核心依赖

```
python>=3.9
pandas>=2.0.0,<3.0.0
numpy>=1.24.0
sqlalchemy>=2.0.0
requests>=2.28.0          # 通达信/币行情 REST 直连
pytdx                      # 内置于 vendor/,无需 pip 安装
```

### Web 界面

```
fastapi>=0.104.0
uvicorn>=0.24.0
pydantic>=2.0.0
python-multipart>=0.0.6
```

### AI 分析（可选）

```
openai>=1.0.0   # OpenAI 兼容 API 客户端
pyyaml>=6.0.0   # YAML 配置文件解析
```

---

## 许可证

MIT License

---

## 参考

- [chan.py](https://github.com/Vespa314/chan.py) - 缠论引擎
- [Tushare Pro](https://tushare.pro) - A股数据接口
- [TradingView Charting Library](https://www.tradingview.com/charting-library/) - 图表（需自行放置到 `web/static/charting_library`，不随仓库分发）
- [Binance Public Market Data](https://developers.binance.com/docs/binance-spot-api-docs) - 币行情镜像
- [Web 文档](http://localhost:8899/docs) - Web API 文档（启动服务后访问）
