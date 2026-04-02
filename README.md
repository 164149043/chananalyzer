# ChanAnalyzer - A股缠论分析系统

> 本项目基于 [Vespa314/chan.py](https://github.com/Vespa314/chan.py) 进行二次开发

**原项目链接**: https://github.com/Vespa314/chan.py | **本项目仓库**: https://github.com/164149043/chananalyzer

---

## 二次开发内容

基于原始 chan.py 项目，本版本进行了以下增强和改进：

- 🤖 **AI 智能分析模块** - 集成多个 AI 模型进行协作分析
- 📡 **多数据源支持** - 支持 Tushare、Akshare 等多种数据源
- 🌐 **FastAPI Web 界面** - 现代化的 Web 分析平台
- ⚡ **缓存优化** - 数据库缓存提升分析速度
- 📊 **可视化增强** - 改进的图表和交互体验

---

基于缠论（缠中说禅）技术分析的 A 股行情分析工具，支持笔、线段、中枢、买卖点自动识别。**仅支持日线级别分析**。

## 特性

- **缠论核心分析**：自动识别笔、线段、中枢结构
- **多买卖点检测**：支持一/二/三类买卖点识别
- **日线分析**：专注日线级别，5年历史数据
- **技术指标**：MACD、量价分析
- **本地缓存**：SQLite 本地缓存，离线快速分析
- **批量扫描**：一键扫描全市场买卖点信号
- **AI 智能分析**：多 AI 协作分析，给出交易策略建议
- **Web 界面**：基于浏览器的一站式分析平台

## 快速开始

### 方式一：Web 界面（推荐）

```bash
# 启动 Web 服务器
python web/start_server.py

# 或直接启动 API
cd web && python api.py
```

然后访问：**http://localhost:8000**

Web 功能包括：
- 📊 **仪表盘** - 市场概况、买卖点统计、热门板块
- 📈 **个股分析** - 输入股票代码，多 AI 协作分析
- ⚡ **买点扫描** - 一买、二买、三买批量扫描
- 💰 **卖点扫描** - 二卖批量扫描
- 📊 **智能筛选** - 行业/地区筛选 + 每日排行榜

### 方式二：命令行

#### 1. 安装依赖

```bash
pip install -r requirements.txt
```

#### 2. 配置 Token

```bash
# Windows PowerShell
$env:TUSHARE_TOKEN="你的token"

# Linux/Mac
export TUSHARE_TOKEN="你的token"
```

> 获取 Token：访问 [Tushare Pro](https://tushare.pro) 注册并获取 API Token

#### 2.5 配置 AI API（可选）

如需使用 AI 智能分析功能，配置 DeepSeek API Key：

```bash
# Windows PowerShell
$env:DEEPSEEK_API_KEY="your_deepseek_key"

# Linux/Mac
export DEEPSEEK_API_KEY="your_deepseek_key"
```

> 获取 API Key：访问 [DeepSeek Platform](https://platform.deepseek.com/api_keys) 注册并获取 API Key

#### 3. 运行分析

```python
from ChanAnalyzer import ChanAnalyzer

analyzer = ChanAnalyzer(code="000001")
print(analyzer.get_summary())
```

---

## 命令行使用

### 扫描器选择

系统提供两种扫描器，可根据需求选择：

| 扫描器 | 数据源 | 速度 | 功能 | 适用场景 |
|--------|--------|------|------|----------|
| `scan_stocks_cache.py` | 本地数据库 + Tushare | **快** | 买卖点+行业/地区+资金流向 | **推荐日常使用** |
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

# 按地区筛选
python scan_stocks_cache.py --area 深圳 上海

# 排除ST股票
python scan_stocks_cache.py --exclude-st

# 显示资金流向并排序
python scan_stocks_cache.py --show-money-flow --sort-by-money-flow

# 筛选特定买点
python scan_stocks_cache.py --buy 1 2 3a

# 保存结果
python scan_stocks_cache.py --output results.txt

# 按行业分组显示
python scan_stocks_cache.py --group-by industry

# 组合使用：电子行业 + 二买三买 + 主力流入
python scan_stocks_cache.py --industry 电子 --buy 2 3a 3b --min-money-flow 500 --sort-by-money-flow
```

### 首次使用完整流程

```bash
# 1. 同步股票基本信息（名称、行业、地区）- 首次使用必做
python -m scripts.cache_stock_info

# 2. 缓存日线数据（5年）
python -m scripts.cache_all_stocks --all --kl-types DAY --begin 2021-04-01 --delay 0.3

# 3. 测试扫描
python scan_stocks_cache.py --codes 000001 000002 600000
```

### 分析单只股票

```bash
# 查看文本摘要
python -c "
from ChanAnalyzer import ChanAnalyzer
analyzer = ChanAnalyzer(code='000001')
print(analyzer.get_summary())
"
```

### AI 智能分析

系统提供两种 AI 分析模式：

#### 单 AI 分析

```bash
# 交互模式
python -m scripts.ai_analyze

# 命令行模式
python -m scripts.ai_analyze --code 000001

# 保存结果
python -m scripts.ai_analyze --code 000001 --output report.txt
```

#### 多 AI 协作分析（推荐）

两个分析师 AI 并行分析 + 一个决策者 AI 综合判断：

```bash
# 基本用法
python -m scripts.multi_ai_analyze --code 000001

# 使用自定义配置
python -m scripts.multi_ai_analyze --code 000001 --config my_config.yaml

# 保存结果
python -m scripts.multi_ai_analyze --code 000001 --output report.txt
```

**多 AI 分析流程**：
```
缠论数据 → [分析师A + 分析师B] 并行分析 → 决策者综合 → 最终建议
           (deepseek-chat)                   (deepseek-reasoner)
           温度: 0.4 / 0.7
```

**配置文件** (`ai_config.yaml`)：

```yaml
# 分析师配置
analysts:
  model: deepseek-chat
  temperatures: [0.4, 0.7]  # 两个分析师的温度
  max_tokens: 2000

# 决策者配置
decision_maker:
  model: deepseek-reasoner
  temperature: 0.3
  max_tokens: 2000

# 提示词配置
prompts:
  analyst_system: |
    你是一位专业的股票技术分析师，精通缠论理论...
  decision_maker_system: |
    你是一位资深的投资决策专家...
```

### Web 界面

基于浏览器的现代化分析平台。

#### 启动 Web 服务

```bash
# 方式1：使用启动脚本（推荐）
python web/start_server.py

# 方式2：直接运行 API
cd web && python api.py

# 局域网访问
python -m uvicorn web.api:app --host 0.0.0.0
```

然后访问：**http://localhost:8000**

#### 功能模块

| 模块 | 功能 | 说明 |
|------|------|------|
| 📊 仪表盘 | 市场概览 | 指数概览、买卖点统计、热门板块、买点推荐 |
| 📈 个股分析 | AI 分析 | 双分析师 + 决策者模式，支持温度调节 |
| ⚡ 买点扫描 | 批量扫描 | 一买、二买、三买 A/B |
| 💰 卖点扫描 | 批量扫描 | 二卖（当前仅支持二卖） |
| 📊 智能筛选 | 行业/地区筛选 | 按行业和地区筛选股票，支持每日排行榜 |

#### Web API 端点

```bash
# 买卖点扫描 API
POST /api/scan/buy/start   # 启动买点扫描
POST /api/scan/sell/start  # 启动卖点扫描
GET  /api/scan/status      # 获取扫描状态
GET  /api/scan/buy/results # 获取买点扫描结果
GET  /api/scan/sell/results # 获取卖点扫描结果

# 个股分析 API
POST /api/stock/analyze       # AI 分析股票（SSE 流式）
GET  /api/ai/config        # 获取 AI 配置

# 股票信息 API
GET  /api/stock/info/:code # 获取股票信息
GET  /api/stock/analysis/:code # 获取股票分析数据

# 筛选和排行 API
GET  /api/industries        # 获取行业列表及股票数量
GET  /api/areas             # 获取地区列表及股票数量
GET  /api/ranking           # 获取每日排行榜（涨跌幅/成交额/换手率）
```

### 数据缓存管理

#### 首次批量缓存

```bash
# 缓存5年日线数据（推荐）
python -m scripts.cache_all_stocks --all --kl-types DAY --begin 2021-04-01 --delay 0.3

# 测试：先缓存 100 只股票
python -m scripts.cache_all_stocks --all --kl-types DAY --begin 2021-04-01 --limit 100 --delay 0.3

# 缓存指定股票
python -m scripts.cache_all_stocks --codes 000001 000002 --kl-types DAY
```

**参数说明**：
- `--kl-types DAY` - 缓存日线（推荐：约 5000 次调用）
- `--begin 2021-04-01` - 从5年前开始获取
- `--delay 0.3` - 每股间隔 0.3 秒，避免触发频次限制
- `--limit 100` - 限制数量，测试用

#### 日常更新数据

```bash
# 更新所有已缓存的股票（每日收盘后执行）
python -m scripts.update_data --all

# 更新指定股票
python -m scripts.update_data --codes 000001 000002

# 清除缓存后重新获取
python -m scripts.update_data --codes 000001 --refresh
```

---

## 项目结构

```
chan.py/
├── ChanAnalyzer/           # 分析模块
│   ├── analyzer.py         # 核心分析器（仅日线）
│   ├── ai_analyzer.py      # AI分析器
│   ├── multi_ai_analyzer.py # 多AI协作分析器
│   ├── prompts/            # AI提示词模板
│   │   ├── analyst.py      # 分析师提示词
│   │   └── decision_maker.py # 决策者提示词
│   ├── database.py         # 数据库模型
│   ├── data_manager.py     # 数据管理器
│   └── formatter.py        # 格式化输出
├── Common/                 # 公共模块
│   ├── CEnum.py           # 枚举定义
│   └── CTime.py           # 时间处理
├── KLine/                  # K线处理
├── Bi/                     # 笔
├── Seg/                    # 线段
├── Zs/                     # 中枢
├── DataAPI/                # 数据源
│   ├── TushareAPI.py      # Tushare 接口
│   └── CacheDBAPI.py      # 本地数据库接口
├── web/                    # Web界面
│   ├── api.py             # FastAPI 后端
│   ├── start_server.py    # 服务器启动脚本
│   ├── static/            # 前端静态文件
│   │   ├── index.html     # 主页面
│   │   ├── app.js         # 仪表盘逻辑
│   │   ├── individual.js  # 个股分析逻辑
│   │   └── scan.js        # 扫描功能逻辑
│   └── cache/             # 扫描结果缓存
├── scripts/                # 脚本工具
│   ├── ai_analyze.py      # AI分析脚本
│   ├── multi_ai_analyze.py # 多AI协作分析脚本
│   ├── cache_all_stocks.py # 批量缓存K线数据
│   ├── cache_stock_info.py # 缓存股票基本信息
│   └── update_data.py     # 数据更新脚本
├── scan_stocks.py         # 在线扫描器
├── scan_stocks_cache.py   # 本地缓存扫描器（推荐）
├── ai_config.yaml         # AI配置文件
└── chan.db                # 本地K线缓存数据库
```

---

## 缓存机制

系统使用 SQLite (`chan.db`) 存储历史 K 线数据，避免重复 API 调用：

| 场景 | 首次运行 | 再次运行 |
|------|----------|----------|
| 000001 日线 | 0.25s | 0.01s |
| 加速比 | - | **42.5x** |

### 缓存策略

- **存储位置**: `./chan.db`
- **分析周期**: 仅日线(DAY)
- **数据来源**: Tushare Pro API
- **更新方式**: 使用 `cache_all_stocks.py` 或 `update_data.py`

### Tushare 权限参考

| 权限等级 | 每分钟频次 | 每日总量 | 适用场景 |
|----------|------------|----------|----------|
| 免费账户 | 200 次 | 10,000 次 | 测试、个人使用 |
| 普通用户 | 500 次 | 100,000 次 | **推荐** |

**API 调用估算**：
- 缓存全市场日线5年：~5,000 次调用
- 有缓存后扫描：**0 次**调用

---

## 买卖点类型

| 类型 | 代码 | 说明 | 方向 |
|------|------|------|------|
| 一买 | `1`, `1p` | 第一类买点及衍生 | 买入 |
| 二买 | `2` | 第二类买点 | 买入 |
| 三买A | `3a` | 第三类买点A型 | 买入 |
| 三买B | `3b` | 第三类买点B型 | 买入 |
| 二卖 | `2s` | 第二类卖点 | 卖出 |

> **注意**：当前版本仅支持 **二卖 (2s)** 作为卖点类型。一卖和三卖暂未实现。

### 常用行业名称

| 行业 | 说明 |
|------|------|
| 半导体 | 芯片行业 |
| 元器件 | 电子元器件 |
| 通信设备 | 通信设备制造 |
| 软件 | 软件服务 |
| 电气设备 | 电力设备 |

> 查看完整行业列表：`python scan_stocks.py --list-industries`

---

## 命令参数完整说明

### scan_stocks_cache.py 参数（推荐）

| 参数 | 说明 | 示例 |
|------|------|------|
| `--codes` | 指定股票代码 | `--codes 000001 000002` |
| `--buy` | 筛选买入类型 | `--buy 2 3a 3b` |
| `--sell` | 筛选卖出类型 | `--sell 2s` |
| `--no-strict` | 关闭笔严格模式 | `--no-strict` |
| `--industry` | 按行业筛选 | `--industry 电子 半导体` |
| `--area` | 按地区筛选 | `--area 深圳 上海` |
| `--exclude-st` | 排除ST股票 | `--exclude-st` |
| `--group-by` | 按行业/地区分组 | `--group-by industry` |
| `--show-money-flow` | 显示个股资金流向 | `--show-money-flow` |
| `--sort-by-money-flow` | 按主力净流入排序 | `--sort-by-money-flow` |
| `--min-money-flow` | 最小主力净流入（万元） | `--min-money-flow 1000` |
| `--output` | 保存结果到文件 | `--output results.txt` |

### cache_all_stocks.py 参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--all` | 缓存所有A股 | `--all` |
| `--codes` | 指定股票代码 | `--codes 000001` |
| `--limit` | 限制数量 | `--limit 100` |
| `--kl-types` | K线周期类型 | `--kl-types DAY` |
| `--begin` | 开始日期（默认2023-01-01） | `--begin 2021-04-01` |
| `--delay` | 请求延迟（秒） | `--delay 0.3` |

### update_data.py 参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--all` | 更新所有已缓存股票 | `--all` |
| `--codes` | 指定股票代码 | `--codes 000001` |
| `--kl-types` | K线周期类型 | `--kl-types DAY` |
| `--refresh` | 清除缓存后重新获取 | `--refresh` |
| `--verbose` | 显示详细日志 | `--verbose` |

---

## API 示例

### 日线分析

```python
from ChanAnalyzer import ChanAnalyzer

analyzer = ChanAnalyzer(code="000001")

# 获取文本报告
summary = analyzer.get_summary()

# 获取结构化数据
data = analyzer.get_analysis()

# 获取买卖点
bs_points = analyzer.get_bs_points()
for bs in bs_points:
    direction = "买入" if bs['is_buy'] else "卖出"
    print(f"{bs['type']}类{direction}: {bs['date']} @ {bs['price']:.2f}")
```

### AI 分析

```python
from ChanAnalyzer import ChanAnalyzer, AIAnalyzer, MultiAIAnalyzer
from ChanAnalyzer.sector_flow import get_stock_money_flow

# 获取缠论数据
analyzer = ChanAnalyzer(code="000001")
analysis = analyzer.get_analysis()

# 获取资金流向
money_flow = get_stock_money_flow("000001", days=5)

# 单 AI 分析
ai = AIAnalyzer(provider="deepseek")
result = ai.analyze(analysis, money_flow=money_flow)
print(result)

# 多 AI 协作分析（推荐）
multi_ai = MultiAIAnalyzer()
result = multi_ai.analyze(analysis, money_flow=money_flow)
print(result.decision)

# 查看分析师意见
for opinion in result.analyst_opinions:
    print(f"{opinion.analyst_name}: {opinion.opinion}")
```

---

## 常见问题

### Q: 首次使用应该执行哪些命令？

```bash
# 1. 设置 Token（只需一次）
$env:TUSHARE_TOKEN="你的token"

# 2. 同步股票基本信息
python -m scripts.cache_stock_info

# 3. 缓存5年日线数据
python -m scripts.cache_all_stocks --all --kl-types DAY --begin 2021-04-01 --delay 0.3

# 4. 测试扫描
python scan_stocks_cache.py --codes 000001 000002
```

### Q: 数据获取失败？

**A**: 检查 Tushare Token 是否正确，免费账户有请求频率限制。

### Q: 缓存存储在哪里？

**A**:
- K线数据：`./chan.db`
- 股票信息：`~/.chan/cache/stock_info.json`

### Q: 如何更新所有股票数据？

```bash
python -m scripts.update_data --all
```

### Q: 板块资金流向无法获取？

**A**: 申万行业指数接口需要一定权限，可以：
1. 升级 Tushare 账户权限
2. 或者忽略该功能，直接使用行业筛选

### Q: 个股资金流向需要什么权限？

**A**: 个股资金流向使用 `moneyflow` 接口，需要 **2000 积分**权限。
- 主力资金 = 特大单 + 大单（机构资金流向）
- 散户资金 = 中单 + 小单
- 数据缓存 10 分钟，避免频繁调用

### Q: 扫描结果为什么是 0？

**A**: 可能原因：
1. 未缓存 K 线数据 - 先运行 `python -m scripts.cache_all_stocks --all --kl-types DAY --begin 2021-04-01`
2. 筛选条件过于严格 - 尝试减少选择的买卖点类型
3. 数据库路径问题 - 确保 `chan.db` 在项目根目录

### Q: 扫描结果显示的股票名称和代码一样？

**A**: 需要先同步股票基本信息：

```bash
python -m scripts.cache_stock_info
```

### Q: AI 分析功能如何使用？

**A**:
```bash
# 单 AI 分析
python -m scripts.ai_analyze --code 000001

# 多 AI 协作分析（推荐）
python -m scripts.multi_ai_analyze --code 000001
```

需要设置环境变量 `DEEPSEEK_API_KEY`，获取 API Key: https://platform.deepseek.com/api_keys

### Q: 多 AI 协作分析有什么优势？

**A**:
- 两个分析师 AI 使用不同温度（0.4 / 0.7）并行分析，获得多样化观点
- 决策者 AI（deepseek-reasoner 深度推理模型）综合分析师意见做出最终决策
- 比单 AI 分析更全面、更可靠

---
## 局域网启动命令： 
python -m uvicorn web.api:app --host 0.0.0.0 
python web/start_server.py --host 0.0.0.0
## 依赖项

### 核心依赖

```
python>=3.9
tushare>=1.2.60
pandas>=2.0.0,<3.0.0
numpy>=1.24.0
sqlalchemy>=2.0.0
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

### 安装命令

```bash
# 安装全部依赖
pip install -r requirements.txt

# 仅安装核心依赖
pip install tushare pandas numpy sqlalchemy

# 安装Web界面依赖
pip install fastapi uvicorn pydantic python-multipart

# 安装AI分析依赖
pip install openai pyyaml
```

---

## 许可证

MIT License

---

## 参考

- [chan.py](https://github.com/Vespa314/chan.py) - 缠论
- [Tushare Pro](https://tushare.pro) - 数据接口
- [DeepSeek Platform](https://platform.deepseek.com) - AI API
- [Web 文档](http://localhost:8000/docs) - Web API 文档（启动服务后访问）
