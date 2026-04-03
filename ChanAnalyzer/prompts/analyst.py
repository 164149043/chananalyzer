"""分析师提示词模板"""

ANALYST_SYSTEM_PROMPT = """你是一位专业的股票技术分析师，精通缠论理论。"""


def get_analyst_system_prompt() -> str:
    """获取分析师系统提示词"""
    return ANALYST_SYSTEM_PROMPT


def get_analyst_user_prompt(
    analysis_data: str,
    analyst_id: int
) -> str:
    """
    生成分析师用户提示词

    Args:
        analysis_data: 格式化的缠论数据
        analyst_id: 分析师ID

    Returns:
        完整的用户提示词
    """
    return f"""你是对股票进行缠论分析的分析师{analyst_id + 1}。

请分析以下缠论数据：

{analysis_data}

请给出你的交易策略，包括：
1. 趋势判断
2. 支撑压力位
3. 买卖点分析
4. 风险提示
5. 操作建议

请简明扼要，重点突出。"""
