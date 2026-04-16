"""
AI缠论分析器

将缠论分析数据发送给AI，获取交易策略建议

支持的AI服务：
- DeepSeek: https://api.deepseek.com
- 硅基流动: https://api.siliconflow.cn/v1
"""
import json
import os
from typing import Any, Dict, List, Optional


# AI服务配置
AI_PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-chat", "deepseek-coder"],
        "default_model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "siliconflow": {
        "name": "硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"],
        "default_model": "deepseek-ai/DeepSeek-V3",
        "env_key": "SILICONFLOW_API_KEY",
    },
}


class AIAnalyzer:
    """
    AI缠论分析器

    支持 DeepSeek 和硅基流动 API

    Example:
        >>> from ChanAnalyzer.ai_analyzer import AIAnalyzer
        >>>
        >>> # 使用 DeepSeek
        >>> ai = AIAnalyzer(provider="deepseek")
        >>> result = ai.analyze(analysis_data)
        >>>
        >>> # 使用硅基流动
        >>> ai = AIAnalyzer(provider="siliconflow")
        >>> result = ai.analyze(analysis_data)
    """

    def __init__(
        self,
        provider: str = "deepseek",
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """
        初始化AI分析器

        Args:
            provider: AI服务提供商 (deepseek, siliconflow)
            api_key: API密钥 (默认从环境变量读取)
            model: 模型名称
            base_url: 自定义API端点
        """
        if provider not in AI_PROVIDERS:
            raise ValueError(f"不支持的AI服务: {provider}，请选择: {', '.join(AI_PROVIDERS.keys())}")

        self.provider = provider
        self.provider_config = AI_PROVIDERS[provider]
        self.api_key = api_key or os.environ.get(self.provider_config["env_key"])
        self.model = model or self.provider_config["default_model"]
        self.base_url = base_url or self.provider_config["base_url"]

        if not self.api_key:
            raise ValueError(f"未设置 {self.provider_config['env_key']} 环境变量")

    def format_analysis_data(
        self,
        analysis: Dict[str, Any],
        money_flow: Optional[Dict[str, Any]] = None,
        realtime_quote: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        将缠论分析数据格式化为AI可读的文本

        Args:
            analysis: ChanAnalyzer.get_analysis() 返回的数据
            money_flow: 个股资金流向数据（可选）
            realtime_quote: 盘中实时行情数据（可选）

        Returns:
            格式化的文本描述
        """
        lines = []

        # 基本信息
        code = analysis.get("code", "Unknown")
        lines.append(f"# 股票代码: {code}")

        if realtime_quote and realtime_quote.get('is_trading'):
            lines.append(f"> 盘中交易时段 · 实时行情已接入")

        lines.append("")

        if analysis.get("multi"):
            # 多周期分析
            levels = analysis.get("levels", [])

            # 在顶部显示日线当前价格作为主要参考价格
            day_level = None
            for level in levels:
                if "日线" in level.get("kl_type", ""):
                    day_level = level
                    break

            if day_level:
                close_price = day_level.get('current_price', 0)
                if realtime_quote and realtime_quote.get('is_trading'):
                    rt = realtime_quote
                    lines.append(f"**最新收盘价**: {close_price:.2f}")
                    lines.append(f"**盘中实时价**: {rt['price']:.2f} ({rt['change_pct']:+.2f}%) "
                                 f"[昨收 {rt['prev_close']:.2f}，更新于 {rt['update_time']}]")
                else:
                    lines.append(f"**当前价格（日线收盘）**: {close_price:.2f}")
                lines.append("")

            # 分别显示各周期分析
            for i, level in enumerate(levels):
                lines.extend(self._format_level(level, level_num=i+1, skip_current_price=day_level == level))
                lines.append("")
        else:
            # 单周期分析
            lines.extend(self._format_level(analysis, realtime_quote=realtime_quote))
            lines.append("")

        # 资金流向
        if money_flow:
            lines.extend(self._format_money_flow(money_flow))
            lines.append("")

        return "\n".join(lines)

    def _format_level(self, level: Dict[str, Any], level_num: int = 1, skip_current_price: bool = False, realtime_quote: Optional[Dict[str, Any]] = None) -> List[str]:
        """格式化单级别数据"""
        lines = []

        kl_type = level.get("kl_type", "未知")
        lines.append(f"## {kl_type}分析")
        lines.append("")

        # 时间范围
        lines.append(f"**时间范围**: {level.get('start_date')} ~ {level.get('end_date')}")
        lines.append(f"**K线数量**: {level.get('kline_count')} 根")

        # 当前价格（可选跳过，因为多周期时已在顶部显示日线价格）
        if not skip_current_price:
            close_price = level.get('current_price', 0)
            if realtime_quote and realtime_quote.get('is_trading'):
                rt = realtime_quote
                lines.append(f"**最新收盘价**: {close_price:.2f}")
                lines.append(f"**盘中实时价**: {rt['price']:.2f} ({rt['change_pct']:+.2f}%) "
                             f"[昨收 {rt['prev_close']:.2f}，更新于 {rt['update_time']}]")
            else:
                lines.append(f"**当前价格（日线收盘）**: {close_price:.2f}")
        lines.append("")

        # MACD
        macd = level.get('macd')
        if macd:
            lines.append("**技术指标 (MACD)**:")
            lines.append(f"- MACD: {macd.get('macd', 0):.4f}")
            lines.append(f"- DIF: {macd.get('dif', 0):.4f}")
            lines.append(f"- DEA: {macd.get('dea', 0):.4f}")

            # 判断MACD状态
            macd_val = macd.get('macd', 0)
            dif = macd.get('dif', 0)
            dea = macd.get('dea', 0)

            macd_status = []
            if macd_val > 0:
                macd_status.append("多头区域")
            else:
                macd_status.append("空头区域")

            if dif > dea:
                macd_status.append("金叉(向上)")
            else:
                macd_status.append("死叉(向下)")

            # 简单背离判断
            if len(macd_status) > 0:
                lines.append(f"- 状态: {', '.join(macd_status)}")
            lines.append("")

        # K线高低点统计
        kline_range = level.get('kline_range')
        if kline_range and kline_range.get('status') != '无K线数据':
            lines.append(f"**近{kline_range['period']}根K线统计**:")
            lines.append(f"- 区间高点: {kline_range['period_high']:.2f}")
            lines.append(f"- 区间低点: {kline_range['period_low']:.2f}")
            lines.append(f"- 当前价格位置: {kline_range['position_pct']:.1f}% (0%=最低, 100%=最高)")
            lines.append(f"- 距高点: {kline_range['dist_high_pct']:+.2f}%")
            lines.append(f"- 距低点: {kline_range['dist_low_pct']:+.2f}%")
            lines.append("")

        # 买卖点
        buy_signals = level.get('buy_signals', [])
        sell_signals = level.get('sell_signals', [])

        lines.append("**买卖点统计**:")
        lines.append(f"- 买入点: {len(buy_signals)} 个")
        lines.append(f"- 卖出点: {len(sell_signals)} 个")

        # 最近买入点详情
        if buy_signals:
            lines.append("")
            lines.append(f"**买入点明细** (共{len(buy_signals)}个):")
            for bs in buy_signals:
                bs_type = bs.get('type', 'Unknown')
                date = bs.get('date', '')
                price = bs.get('price', 0)
                lines.append(f"  - {bs_type}: {date} @ {price:.2f}")

        # 最近卖出点详情
        if sell_signals:
            lines.append("")
            lines.append(f"**卖出点明细** (共{len(sell_signals)}个):")
            for bs in sell_signals:
                bs_type = bs.get('type', 'Unknown')
                date = bs.get('date', '')
                price = bs.get('price', 0)
                lines.append(f"  - {bs_type}: {date} @ {price:.2f}")
        lines.append("")

        # 笔
        bi_list = level.get('bi_list', [])
        if bi_list:
            lines.append(f"**笔列表** (最近20个，共{len(bi_list)}个):")
            for bi in bi_list[-20:]:
                direction = bi['dir']
                start_date = bi['start_date']
                end_date = bi['end_date']
                start_price = bi['start_price']
                end_price = bi['end_price']
                sure = "已确认" if bi.get('is_sure') else "未确认"

                # 计算涨跌幅
                change_pct = ((end_price - start_price) / start_price * 100) if start_price > 0 else 0
                change_str = f"({change_pct:+.2f}%)"

                lines.append(f"  - {direction}: {start_date} -> {end_date}, "
                           f"{start_price:.2f} -> {end_price:.2f} {change_str} ({sure})")
            lines.append("")

        # 线段
        seg_list = level.get('seg_list', [])
        if seg_list:
            lines.append(f"**线段列表** (最近20个，共{len(seg_list)}个):")
            for seg in seg_list[-20:]:
                direction = seg['dir']
                start_date = seg['start_date']
                end_date = seg['end_date']
                start_price = seg['start_price']
                end_price = seg['end_price']
                bi_count = seg['bi_count']
                sure = "已确认" if seg.get('is_sure') else "未确认"

                change_pct = ((end_price - start_price) / start_price * 100) if start_price > 0 else 0
                change_str = f"({change_pct:+.2f}%)"

                lines.append(f"  - {direction}: {start_date} -> {end_date}, "
                           f"{start_price:.2f} -> {end_price:.2f} {change_str} "
                           f"({bi_count}笔, {sure})")
            lines.append("")

        # 中枢
        zs_list = level.get('zs_list', [])
        if zs_list:
            show_zs = zs_list[-15:] if len(zs_list) > 15 else zs_list
            lines.append(f"**中枢列表** (最近{len(show_zs)}个，共{len(zs_list)}个):")
            for zs in show_zs:
                zs_idx = zs['idx']
                start_date = zs['start_date']
                end_date = zs['end_date']
                low = zs['low']
                high = zs['high']
                center = zs['center']
                bi_count = zs['bi_count']

                # 计算中枢宽度
                width = high - low
                width_pct = (width / center * 100) if center > 0 else 0

                lines.append(f"  - 中枢{zs_idx}: {start_date} -> {end_date}, "
                           f"区间 [{low:.2f}, {high:.2f}], "
                           f"中心 {center:.2f}, 宽度 {width:.2f}({width_pct:.2f}%), {bi_count}笔")
            lines.append("")

        # 中枢位置
        zs_pos = level.get('zs_position', '')
        lines.append(f"**当前价格位置**: {zs_pos}")
        lines.append("")

        # 成交量分析
        vol_analysis = level.get('volume_analysis', {})
        if vol_analysis:
            lines.append("**成交量分析**:")

            vol_status = vol_analysis.get('vol_status', '')
            if vol_status:
                lines.append(f"- 状态: {vol_status}")

            vol_ratio = vol_analysis.get('vol_ratio', 0)
            if vol_ratio:
                lines.append(f"- 量比: {vol_ratio:.2f}倍")

            vol_price_rel = vol_analysis.get('vol_price_rel', '')
            if vol_price_rel:
                lines.append(f"- 量价关系: {vol_price_rel}")

            # 最近量价分析
            k_vol_price = vol_analysis.get('k_vol_price', [])
            if k_vol_price:
                lines.append("")
                lines.append("**最近5日量价分析**:")
                for i, kvp in enumerate(k_vol_price):
                    desc = kvp.get('desc', '')
                    lines.append(f"  第{5-len(k_vol_price)+i+1}日: {desc}")

            lines.append("")

        return lines

    def _format_money_flow(self, money_flow: Dict[str, Any]) -> List[str]:
        """格式化资金流向数据"""
        lines = []

        if 'error' in money_flow:
            lines.append("## 资金流向")
            lines.append(f"数据获取失败: {money_flow['error']}")
            return lines

        lines.append("## 资金流向分析")
        lines.append("")

        name = money_flow.get('name', '')
        code = money_flow.get('code', '')
        days = money_flow.get('days', 0)

        lines.append(f"**股票**: {name} ({code})")
        lines.append(f"**统计周期**: 近{days}日")
        lines.append("")

        # 主力资金
        net_main = money_flow.get('net_main_amount', 0)
        net_elg = money_flow.get('net_elg_amount', 0)
        net_lg = money_flow.get('net_lg_amount', 0)

        lines.append("**主力资金流向**:")
        lines.append(f"- 主力净流入: {net_main:+,.2f} 万元")

        if net_main > 0:
            lines.append(f"  **状态**: 资金流入，主力看好")
        elif net_main < 0:
            lines.append(f"  **状态**: 资金流出，主力避险")
        else:
            lines.append(f"  **状态**: 资金平衡")

        lines.append(f"  - 特大单净流入: {net_elg:+,.2f} 万元")
        lines.append(f"  - 大单净流入: {net_lg:+,.2f} 万元")
        lines.append("")

        # 散户资金
        net_md = money_flow.get('net_md_amount', 0)
        net_sm = money_flow.get('net_sm_amount', 0)

        lines.append("**散户资金流向**:")
        lines.append(f"- 中单净流入: {net_md:+,.2f} 万元")
        lines.append(f"- 小单净流入: {net_sm:+,.2f} 万元")
        lines.append("")

        # 汇总
        net_amount = money_flow.get('net_amount', 0)
        net_vol = money_flow.get('net_vol', 0)

        lines.append("**汇总**:")
        lines.append(f"- 总净流入: {net_amount:+,.2f} 万元")
        lines.append(f"- 总净流入量: {net_vol:+,} 手")

        # 资金流向评级
        if net_main > 10000:
            level = "**强势流入**"
        elif net_main > 5000:
            level = "**明显流入**"
        elif net_main > 0:
            level = "小幅流入"
        elif net_main > -5000:
            level = "小幅流出"
        elif net_main > -10000:
            level = "明显流出"
        else:
            level = "**大幅流出**"

        lines.append(f"- 资金评级: {level}")
        lines.append("")

        return lines

    def create_prompt(self, analysis_data: str) -> str:
        """
        创建AI分析提示词

        Args:
            analysis_data: 格式化后的缠论数据

        Returns:
            完整的提示词
        """
        prompt = f"""你是一位专业的股票技术分析师，精通缠论理论。请根据以下缠论分析数据，给出专业的交易策略建议。

{analysis_data}

# 分析要求

请从以下几个维度进行专业分析：

## 1. 趋势判断
- 根据笔、线段的方向和结构，判断当前处于什么趋势（上涨/下跌/震荡）
- 判断趋势的强弱和持续性

## 2. 支撑压力位
- 根据中枢区间，指出关键支撑位和压力位
- 给出突破或破位的条件

## 3. 买卖点分析
- 评估最近买卖点的类型和可靠性（一买/二买/三买）
- 当前是否处于合适的买卖时机

## 4. MACD技术指标
- 判断MACD当前状态（金叉/死叉、零轴上/下）
- 是否存在背离现象

## 5. 成交量分析
- 量价配合是否健康
- 放量/缩量对后市的影响

## 6. 资金流向分析
- 主力资金动向（流入/流出）
- 资金面与技术面是否共振

## 7. 风险提示
- 指出当前可能存在的风险点
- 止损位建议

## 8. 操作建议
- 给出明确的操作建议（**买入/卖出/观望**）
- 建议的买入/卖出价格区间
- 建议的仓位控制

请用简明扼要的语言回答，**重点突出操作建议**，格式清晰易读，不要模棱两可。"""
        return prompt

    def analyze(
        self,
        analysis: Dict[str, Any],
        money_flow: Optional[Dict[str, Any]] = None,
        prompt: Optional[str] = None
    ) -> str:
        """
        发送分析请求给AI

        Args:
            analysis: 缠论分析数据
            money_flow: 个股资金流向数据（可选）
            prompt: 自定义提示词（可选）

        Returns:
            AI的分析结果
        """
        # 格式化数据
        analysis_data = self.format_analysis_data(analysis, money_flow)

        # 创建提示词
        if prompt is None:
            prompt = self.create_prompt(analysis_data)

        # 调用AI服务
        return self._call_api(prompt)

    def _call_api(self, prompt: str) -> str:
        """调用AI API（兼容 OpenAI 格式）"""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("请安装 openai 库: pip install openai")

        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一位专业的股票技术分析师，精通缠论理论。请根据缠论数据给出专业的交易建议。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=4000,
            )

            return response.choices[0].message.content

        except Exception as e:
            raise RuntimeError(f"AI API调用失败: {e}")


def analyze_with_ai(
    analysis: Dict[str, Any],
    provider: str = "deepseek",
    money_flow: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """
    便捷函数：使用AI分析缠论数据

    Args:
        analysis: ChanAnalyzer.get_analysis() 返回的数据
        provider: AI服务提供商 (deepseek, siliconflow)
        money_flow: 个股资金流向数据
        api_key: API密钥
        model: 模型名称

    Returns:
        AI的分析结果

    Example:
        >>> from ChanAnalyzer import ChanAnalyzer
        >>> from ChanAnalyzer.ai_analyzer import analyze_with_ai
        >>> from ChanAnalyzer.sector_flow import get_stock_money_flow
        >>>
        >>> analyzer = ChanAnalyzer(code="000001")
        >>> analysis = analyzer.get_analysis()
        >>> money_flow = get_stock_money_flow("000001")
        >>> result = analyze_with_ai(analysis, provider="deepseek", money_flow=money_flow)
        >>> print(result)
    """
    ai_analyzer = AIAnalyzer(
        provider=provider,
        api_key=api_key,
        model=model,
    )
    return ai_analyzer.analyze(analysis, money_flow)


def list_providers():
    """列出支持的AI服务提供商"""
    print("支持的AI服务:")
    print("=" * 60)
    for key, config in AI_PROVIDERS.items():
        print(f"\n{key}:")
        print(f"  名称: {config['name']}")
        print(f"  API地址: {config['base_url']}")
        print(f"  默认模型: {config['default_model']}")
        print(f"  环境变量: {config['env_key']}")
        print(f"  可用模型: {', '.join(config['models'])}")
