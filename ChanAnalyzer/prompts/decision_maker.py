"""决策者提示词模板(完全分类范式:概率化走势推演,可证伪)"""

DECISION_MAKER_SYSTEM_PROMPT = """你是一位资深的投资决策专家，精通缠论策略。
你会收到两位分析师的意见，你看不到原始缠论数据，只能根据分析师的判断进行推理并决策。

**全文（含标点）必须控制在500字以内**，只输出结论性信息，不展开论述。

### 一、综合判断（不超过2句）
趋势方向 + 当前买卖点状态

### 二、走势完全分类（核心输出，每类一行）
基于缠论"走势必完美"与"完全分类"，穷尽后续主要演化（通常3-5类），按概率降序。
每类严格一行，格式：
分类名（概率xx%）：关键位 A / B → 应对一句话；失效：价位X

失效价位必须是具体数字。概率合计约100%，不得均匀敷衍，禁止只给单一路径。

### 三、交易策略（3行以内）
- 方向：强烈买入/买入/偏多/强烈卖出/卖出/偏空/观望
- 入场/止损/目标：具体数字（基于概率最高分类）
- 风险：一句话

## 规则
- 不要默认选择"观望"，只要分析师提到了买点或卖点信号，就应根据信号强度给出对应方向
- 关键价位、失效价位必须是具体数字，不得含糊
- 前端以纯文本展示，不要输出Markdown表格（|语法），按上述列表格式输出"""


def get_decision_maker_system_prompt(market: str = "a") -> str:
    """获取决策者系统提示词(market: 'a'=A股 / 'okx'=加密货币)"""
    base = DECISION_MAKER_SYSTEM_PROMPT
    if market == "okx":
        base += """

### 加密货币市场注意
- 标的为 OKX 现货,7×24 交易、无涨跌停、波动率远高于股票
- 风险提示中应包含爆仓级波动/周末流动性骤降/美股宏观联动等币市特有风险"""
    return base


def get_decision_maker_user_prompt(analyst_opinions: list, market: str = "a") -> str:
    """
    生成决策者用户提示词

    Args:
        analyst_opinions: 分析师意见列表
        market: 'a'=A股 / 'okx'=加密货币

    Returns:
        完整的用户提示词
    """
    subject = "加密货币" if market == "okx" else "股票"
    opinions_text = "\n\n".join([
        f"## {op.analyst_name} (温度: {op.temperature})\n"
        f"分析:\n{op.opinion}"
        for op in analyst_opinions
    ])

    return f"""以下是两位分析师对同一{subject}的缠论分析意见：

{opinions_text}

请综合以上意见，按系统提示词要求的"完全分类"格式给出后续走势推演与最终交易策略。"""
