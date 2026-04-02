"""决策者提示词模板"""

DECISION_MAKER_SYSTEM_PROMPT = """你是一位资深的投资决策专家，精通缠论策略。
你会收到两位分析师的意见，你看不到原始缠论数据，只能根据分析师的判断进行推理并决策。"""


def get_decision_maker_system_prompt() -> str:
    """获取决策者系统提示词"""
    return DECISION_MAKER_SYSTEM_PROMPT


def get_decision_maker_user_prompt(analyst_opinions: list) -> str:
    """
    生成决策者用户提示词

    Args:
        analyst_opinions: 分析师意见列表

    Returns:
        完整的用户提示词
    """
    opinions_text = "\n\n".join([
        f"## {op.analyst_name} (温度: {op.temperature})\n"
        f"分析:\n{op.opinion}"
        for op in analyst_opinions
    ])

    return f"""以下两位分析师对同一只股票的缠论分析意见：

{opinions_text}

请综合以上两位分析师的意见进行推理，给出最终的交易决策：

1. 给出明确的操作方向（买入/卖出/观望）
2. 给出建议的价格区间和仓位

请简明扼要，**最终决策要明确**，不要模棱两可。"""
