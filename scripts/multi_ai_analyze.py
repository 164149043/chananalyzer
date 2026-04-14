"""
多AI协作缠论分析脚本

使用方法:
    # 命令行模式
    python -m scripts.multi_ai_analyze --code 000001

    # 多周期分析
    python -m scripts.multi_ai_analyze --code 000001 --multi

    # 使用自定义配置
    python -m scripts.multi_ai_analyze --code 000001 --config my_config.yaml
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ChanAnalyzer import ChanAnalyzer, MultiAIAnalyzer
from ChanAnalyzer.sector_flow import get_stock_money_flow


def check_api_key(config_path: str = None) -> bool:
    """根据配置文件检查对应的API密钥"""
    import yaml

    # 默认配置文件路径
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'ai_config.yaml'
        )

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"\n错误: 配置文件不存在: {config_path}")
        return False

    provider = config.get('provider', {})
    api_key_env = provider.get('api_key_env', 'DEEPSEEK_API_KEY')
    provider_name = provider.get('name', 'deepseek')
    base_url = provider.get('base_url', '')

    if not os.environ.get(api_key_env):
        print(f"\n错误: 未设置 {api_key_env} 环境变量")
        print("请先设置API密钥:")
        print(f"  Windows PowerShell: $env:{api_key_env}='your_key'")
        print(f"  Linux/Mac: export {api_key_env}='your_key'")
        if base_url:
            print(f"\n当前AI服务: {provider_name} ({base_url})")
        return False
    return True


def command_mode(args):
    """命令行模式"""
    if not check_api_key(args.config):
        return

    code = args.code
    config_path = args.config

    print(f"\n正在分析: {code}")
    print("AI服务: 多AI协作")
    print("-" * 60)

    try:
        import time

        # 执行缠论分析（日线）
        t0 = time.time()
        analyzer = ChanAnalyzer(
            code=code,
            begin_date=args.begin_date,
            end_date=args.end_date,
        )

        analysis = analyzer.get_analysis()
        t1 = time.time()
        print(f"  缠论计算耗时: {t1-t0:.2f}秒")

        # 获取资金流向
        money_flow = None
        if not args.no_money_flow:
            print("正在获取资金流向...")
            try:
                money_flow = get_stock_money_flow(code, days=5)
                if 'error' not in money_flow:
                    name = money_flow.get('name', code)
                    net_main = money_flow.get('net_main_amount', 0)
                    print(f"{name} 主力净流入: {net_main:+,.2f} 万元")
            except Exception as e:
                print(f"资金流向获取失败: {e}")

        t2 = time.time()

        # 多AI分析
        print("\n正在格式化缠论数据...")

        ai = MultiAIAnalyzer(config_path=config_path)

        # 打印发送给AI的原始缠论数据
        analysis_data = ai.format_analysis_data(analysis, money_flow)
        print("\n【发送给AI的原始缠论数据】")
        print("=" * 60)
        print(analysis_data)
        print("=" * 60)

        t3 = time.time()
        print(f"  数据准备耗时: {t3-t2:.2f}秒")
        print("\n正在发送给AI分析...")
        print("-" * 60)

        result = ai.analyze(analysis, money_flow)

        # 打印结果
        ai.print_result(result)

        # 详细耗时汇总
        print(f"\n--- 详细耗时 ---")
        print(f"  缠论计算: {t1-t0:.2f}秒")
        print(f"  数据准备: {t3-t2:.2f}秒")
        for opinion in result.analyst_opinions:
            print(f"  {opinion.analyst_name} ({opinion.model}): {opinion.elapsed:.2f}秒")
        print(f"  AI决策者: {result.timing['decision_maker']:.2f}秒")
        print(f"  总计: {t3-t0 + result.timing['total']:.2f}秒")

        # 保存到文件
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(f"# {code} 多AI协作分析报告\n\n")

                # 写入原始缠论数据
                f.write("## 发送给AI的原始缠论数据\n\n")
                f.write("```\n")
                f.write(analysis_data)
                f.write("\n```\n\n")

                # 写入分析师意见
                for opinion in result.analyst_opinions:
                    f.write(f"## {opinion.analyst_name} (温度: {opinion.temperature})\n\n")
                    f.write(f"{opinion.opinion}\n\n")

                # 写入最终决策
                f.write(f"## 最终决策\n\n")
                f.write(f"{result.decision}\n")
            print(f"\n结果已保存到: {args.output}")

    except Exception as e:
        print(f"\n分析失败: {e}")
        import traceback
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(
        description="多AI协作缠论分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 命令行模式
  python -m scripts.multi_ai_analyze --code 000001

  # 多周期分析
  python -m scripts.multi_ai_analyze --code 000001 --multi

  # 使用自定义配置
  python -m scripts.multi_ai_analyze --code 000001 --config my_config.yaml

环境变量:
  根据ai_config.yaml中provider.api_key_env配置对应的API密钥
        """
    )

    parser.add_argument('--code', help='股票代码')
    parser.add_argument('--begin-date', help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--no-money-flow', action='store_true', help='不获取资金流向')
    parser.add_argument('--config', help='配置文件路径 (默认: ai_config.yaml)')
    parser.add_argument('--output', help='保存分析结果到文件')

    args = parser.parse_args()

    if not args.code:
        parser.print_help()
        print("\n提示: 使用 --code 指定股票代码")
        return

    try:
        command_mode(args)
    except KeyboardInterrupt:
        print("\n\n程序已中断")


if __name__ == "__main__":
    main()
