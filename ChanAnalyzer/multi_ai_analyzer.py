"""
多AI协作缠论分析器

架构：
1. 两个分析师AI并行分析缠论数据
2. 一个决策者AI综合分析师意见做最终决策
"""
import os
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass


@dataclass
class AnalystOpinion:
    """分析师意见"""
    analyst_id: int
    analyst_name: str
    model: str
    temperature: float
    opinion: str
    elapsed: float = 0.0  # 单个分析师耗时（秒）


@dataclass
class MultiAIResult:
    """多AI分析结果"""
    # 分析师意见
    analyst_opinions: List[AnalystOpinion]

    # 决策者意见
    decision: str

    # 耗时统计
    timing: Dict[str, float]


class MultiAIAnalyzer:
    """
    多AI协作缠论分析器

    Example:
        >>> from ChanAnalyzer.multi_ai_analyzer import MultiAIAnalyzer
        >>>
        >>> # 使用默认配置
        >>> analyzer = MultiAIAnalyzer()
        >>> result = analyzer.analyze(analysis_data, money_flow)
        >>> print(result.decision)
        >>>
        >>> # 使用自定义配置
        >>> analyzer = MultiAIAnalyzer(config_path="my_config.yaml")
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化多AI分析器

        Args:
            config_path: 配置文件路径（默认: ai_config.yaml）
        """
        self.config = self._load_config(config_path)
        self._init_client()

    def _load_config(self, config_path: Optional[str] = None) -> Dict:
        """加载配置文件"""
        if config_path is None:
            # 默认查找项目根目录的配置文件
            project_root = Path(__file__).parent.parent
            config_path = project_root / "ai_config.yaml"

        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _init_client(self):
        """初始化OpenAI客户端（同步 + 异步）"""
        try:
            from openai import OpenAI, AsyncOpenAI
        except ImportError:
            raise ImportError("请安装 openai 库: pip install openai")

        provider_config = self.config['provider']
        api_key = os.environ.get(provider_config['api_key_env'])

        if not api_key:
            raise ValueError(f"请设置 {provider_config['api_key_env']} 环境变量")

        self.client = OpenAI(
            api_key=api_key,
            base_url=provider_config['base_url'],
        )
        self.async_client = AsyncOpenAI(
            api_key=api_key,
            base_url=provider_config['base_url'],
        )

    def format_analysis_data(
        self,
        analysis: Dict[str, Any],
        money_flow: Optional[Dict[str, Any]] = None,
        realtime_quote: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        将缠论分析数据格式化为AI可读的文本

        复用 AIAnalyzer.format_analysis_data() 的逻辑
        """
        from ChanAnalyzer.ai_analyzer import AIAnalyzer
        ai = AIAnalyzer(provider=self.config['provider']['name'])
        return ai.format_analysis_data(analysis, money_flow, realtime_quote)

    def _create_analyst_prompt(
        self,
        analysis_data: str,
        analyst_id: int
    ) -> tuple:
        """创建分析师提示词（使用 prompts 模块）"""
        from ChanAnalyzer.prompts.analyst import get_analyst_system_prompt, get_analyst_user_prompt
        system_prompt = get_analyst_system_prompt()
        user_prompt = get_analyst_user_prompt(analysis_data, analyst_id + 1)
        return system_prompt, user_prompt

    def _create_decision_maker_prompt(
        self,
        analyst_opinions: List[AnalystOpinion]
    ) -> tuple:
        """创建决策者提示词（使用 prompts 模块）"""
        from ChanAnalyzer.prompts.decision_maker import get_decision_maker_system_prompt, get_decision_maker_user_prompt
        system_prompt = get_decision_maker_system_prompt()
        user_prompt = get_decision_maker_user_prompt(analyst_opinions)
        return system_prompt, user_prompt

    def _call_analyst(
        self,
        analyst_id: int,
        system_prompt: str,
        user_prompt: str
    ) -> AnalystOpinion:
        """调用单个分析师API"""
        config = self.config['analysts']
        models = config['models']
        temperatures = config['temperatures']

        # 按分析师ID选择对应的模型和温度
        model = models[analyst_id] if analyst_id < len(models) else models[-1]
        temperature = temperatures[analyst_id] if analyst_id < len(temperatures) else temperatures[-1]

        import time
        t0 = time.time()
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
            max_tokens=config['max_tokens'],
        )
        elapsed = time.time() - t0

        return AnalystOpinion(
            analyst_id=analyst_id,
            analyst_name=f"分析师{chr(65 + analyst_id)}",  # 分析师A, 分析师B
            model=model,
            temperature=temperature,
            opinion=response.choices[0].message.content,
            elapsed=elapsed,
        )

    def _call_decision_maker(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> str:
        """调用决策者API"""
        config = self.config['decision_maker']

        response = self.client.chat.completions.create(
            model=config['model'],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=config['temperature'],
            max_tokens=config['max_tokens'],
        )

        return response.choices[0].message.content

    def analyze(
        self,
        analysis: Dict[str, Any],
        money_flow: Optional[Dict[str, Any]] = None,
        realtime_quote: Optional[Dict[str, Any]] = None
    ) -> MultiAIResult:
        """
        执行多AI协作分析

        Args:
            analysis: ChanAnalyzer.get_analysis() 返回的数据
            money_flow: 个股资金流向数据（可选）
            realtime_quote: 盘中实时行情数据（可选）

        Returns:
            MultiAIResult 包含分析师意见和最终决策
        """
        import time
        timing = {}

        # 1. 格式化缠论数据
        analysis_data = self.format_analysis_data(analysis, money_flow, realtime_quote)

        # 2. 并行调用分析师
        start_time = time.time()

        analyst_opinions = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {}
            for i in range(self.config['analysts']['count']):
                system_prompt, user_prompt = self._create_analyst_prompt(
                    analysis_data, i
                )
                future = executor.submit(
                    self._call_analyst, i, system_prompt, user_prompt
                )
                futures[future] = i

            for future in as_completed(futures):
                opinion = future.result()
                analyst_opinions.append(opinion)

        timing['analysts'] = time.time() - start_time

        # 3. 调用决策者
        start_time = time.time()

        system_prompt, user_prompt = self._create_decision_maker_prompt(
            analyst_opinions
        )
        decision = self._call_decision_maker(system_prompt, user_prompt)

        timing['decision_maker'] = time.time() - start_time
        timing['total'] = timing['analysts'] + timing['decision_maker']

        return MultiAIResult(
            analyst_opinions=analyst_opinions,
            decision=decision,
            timing=timing
        )

    def print_result(self, result: MultiAIResult):
        """打印分析结果"""
        print("\n" + "=" * 70)
        print("多AI协作分析报告")
        print("=" * 70)

        # 分析师意见
        for opinion in result.analyst_opinions:
            print(f"\n【{opinion.analyst_name}】")
            print(f"模型: {opinion.model} (温度: {opinion.temperature}, 耗时: {opinion.elapsed:.2f}秒)")
            print("-" * 70)
            print(opinion.opinion)

        # 最终决策
        print("\n" + "=" * 70)
        print("【最终决策】")
        print("=" * 70)
        print(result.decision)

        # 耗时
        if self.config['output'].get('show_timing', True):
            print("\n" + "-" * 70)
            print(f"分析耗时: {result.timing['analysts']:.2f}秒")
            print(f"决策耗时: {result.timing['decision_maker']:.2f}秒")
            print(f"总计耗时: {result.timing['total']:.2f}秒")


# 便捷函数
def analyze_with_multi_ai(
    analysis: Dict[str, Any],
    money_flow: Optional[Dict[str, Any]] = None,
    config_path: Optional[str] = None
) -> MultiAIResult:
    """
    使用多AI协作分析缠论数据

    Args:
        analysis: ChanAnalyzer.get_analysis() 返回的数据
        money_flow: 个股资金流向数据
        config_path: 配置文件路径

    Returns:
        MultiAIResult 分析结果
    """
    analyzer = MultiAIAnalyzer(config_path)
    return analyzer.analyze(analysis, money_flow)
