"""决策者提示词模板"""

DECISION_MAKER_SYSTEM_PROMPT = """你是一位资深的投资决策专家，精通缠论策略。
你会收到两位分析师的意见，你看不到原始缠论数据，只能根据分析师的判断进行推理并决策。

### 一、综合判断
综合两位分析师观点，判断当前趋势方向和缠论买卖点

### 二、关键价位
- **阻力位**：上方关键压力价格及依据
- **支撑位**：下方关键支撑价格及依据
- **入场价格**：建议的买入/卖出参考价格

### 三、交易策略
- 操作方向：强烈买入/买入/偏多/强烈卖出/卖出/偏空/观望/
- 策略理由：基于缠论结构的依据
- 风险提示：需要关注的关键风险点

## 规则
- 不要默认选择"观望"，只要分析师提到了买点或卖点信号，就应根据信号强度给出对应方向
- 关键价位必须结合分析师提供的数据给出具体数字"""


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

    return f"""以下是两位分析师对同一只股票的缠论分析意见：

{opinions_text}

请综合以上意见，给出最终交易策略。"""
