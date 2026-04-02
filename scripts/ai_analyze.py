"""
AI缠论分析脚本

交互式输入股票代码，获取缠论数据后发送给AI分析，给出交易策略

支持的AI服务：
- DeepSeek: https://api.deepseek.com
- 硅基流动: https://api.siliconflow.cn/v1

使用方法:
    # 使用 DeepSeek（默认）
    python -m scripts.ai_analyze

    # 使用硅基流动
    python -m scripts.ai_analyze --provider siliconflow

    # 命令行模式
    python -m scripts.ai_analyze --code 000001 --provider deepseek
"""
import os
import sys
import argparse

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Common.CEnum import KL_TYPE
from ChanAnalyzer import ChanAnalyzer, AIAnalyzer
from ChanAnalyzer.sector_flow import get_stock_money_flow


def print_banner():
    """打印横幅"""
    print("=" * 60)
    print("           AI缠论分析工具")
    print("=" * 60)


def get_stock_code() -> str:
    """获取股票代码输入"""
    while True:
        code = input("\n请输入股票代码（如 000001，输入 q 退出）: ").strip()
        if code.lower() == 'q':
            return None
        if code and code.isdigit():
            return code.zfill(6)
        print("请输入有效的股票代码（6位数字）")


def get_date_range() -> tuple:
    """获取日期范围"""
    print("\n日期范围（留空使用默认值）")
    begin = input("  开始日期 (格式: YYYY-MM-DD，默认近1年): ").strip()
    end = input("  结束日期 (格式: YYYY-MM-DD，默认至今): ").strip()
    return begin or None, end or None


def get_analysis_type() -> str:
    """获取分析类型（仅日线）"""
    print("\n分析类型: 日线")
    return "1"


def get_provider() -> str:
    """获取AI服务提供商"""
    print("\n选择AI服务:")
    print("  1. DeepSeek (推荐)")
    print("  2. 硅基流动")

    while True:
        choice = input("请选择 (1-2，默认 1): ").strip() or "1"
        if choice == '1':
            return "deepseek"
        elif choice == '2':
            return "siliconflow"
        print("请输入有效选项 1-2")


def check_api_key(provider: str) -> bool:
    """检查API密钥是否已设置"""
    env_keys = {
        "deepseek": "DEEPSEEK_API_KEY",
        "siliconflow": "SILICONFLOW_API_KEY",
    }
    key = env_keys.get(provider, "")

    if os.environ.get(key):
        return True

    print(f"\n错误: 未设置 {key} 环境变量")
    print("请先设置API密钥:")

    if provider == "deepseek":
        print("  Windows PowerShell: $env:DEEPSEEK_API_KEY='your_key'")
        print("  Linux/Mac: export DEEPSEEK_API_KEY='your_key'")
        print("\n获取API密钥: https://platform.deepseek.com/api_keys")
    else:
        print("  Windows PowerShell: $env:SILICONFLOW_API_KEY='your_key'")
        print("  Linux/Mac: export SILICONFLOW_API_KEY='your_key'")
        print("\n获取API密钥: https://cloud.siliconflow.cn/account/ak")

    return False


def print_ai_result(result: str):
    """打印AI分析结果"""
    print("\n" + "=" * 60)
    print("AI分析结果")
    print("=" * 60)
    print(result)
    print("=" * 60)


def interactive_mode(args):
    """交互模式"""
    print_banner()

    # 获取AI服务提供商
    provider = args.provider or get_provider()

    # 检查API密钥
    if not check_api_key(provider):
        return

    while True:
        # 获取股票代码
        code = get_stock_code()
        if code is None:
            print("\n退出程序")
            break

        print(f"\n{'='*60}")
        print(f"正在分析: {code}")
        print(f"AI服务: {provider.upper()}")
        print("=" * 60)

        try:
            # 获取分析类型
            analysis_type = get_analysis_type()

            # 获取日期范围
            begin_date, end_date = get_date_range()

            # 是否获取资金流向
            get_flow = input("\n是否获取资金流向数据? (Y/n): ").strip().lower() != 'n'

            print(f"\n正在获取数据...")
            print("-" * 40)

            # 执行缠论分析（日线）
            analyzer = ChanAnalyzer(
                code=code,
                begin_date=begin_date,
                end_date=end_date,
            )
            analysis = analyzer.get_analysis()

            # 获取资金流向
            money_flow = None
            if get_flow:
                print("\n正在获取资金流向...")
                try:
                    money_flow = get_stock_money_flow(code, days=5)
                    if 'error' in money_flow:
                        print(f"  资金流向获取失败: {money_flow['error']}")
                    else:
                        name = money_flow.get('name', code)
                        net_main = money_flow.get('net_main_amount', 0)
                        print(f"  {name} 主力净流入: {net_main:+,.2f} 万元")
                except Exception as e:
                    print(f"  资金流向获取失败: {e}")

            # 显示缠论数据摘要
            print("\n缠论分析完成!")
            if analysis.get("multi"):
                for level in analysis.get("levels", []):
                    kl_type = level.get("kl_type", "")
                    print(f"  {kl_type}: K线{level.get('kline_count')}根, "
                          f"买入{len(level.get('buy_signals', []))}点, "
                          f"卖出{len(level.get('sell_signals', []))}点")
            else:
                print(f"  K线: {analysis.get('kline_count')}根")
                print(f"  买入点: {len(analysis.get('buy_signals', []))}个")
                print(f"  卖出点: {len(analysis.get('sell_signals', []))}个")

            # AI分析
            print("\n正在发送给AI分析...")
            print("-" * 40)

            ai = AIAnalyzer(provider=provider)

            result = ai.analyze(analysis, money_flow=money_flow)

            # 打印结果
            print_ai_result(result)

        except Exception as e:
            print(f"\n分析失败: {e}")
            import traceback
            traceback.print_exc()

        # 询问是否继续
        print("\n" + "=" * 60)
        cont = input("是否继续分析其他股票? (Y/n): ").strip().lower()
        if cont == 'n':
            print("\n退出程序")
            break


def command_mode(args):
    """命令行模式"""
    code = args.code
    if not code:
        print("错误: 命令行模式需要指定 --code 参数")
        return

    provider = args.provider or "deepseek"

    # 检查API密钥
    if not check_api_key(provider):
        return

    print(f"正在分析: {code}")
    print(f"AI服务: {provider.upper()}")
    print("-" * 40)

    try:
        # 执行缠论分析（日线）
        analyzer = ChanAnalyzer(
            code=code,
            begin_date=args.begin_date,
            end_date=args.end_date,
            )

        analysis = analyzer.get_analysis()

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

        # AI分析
        print("正在发送给AI分析...")
        ai = AIAnalyzer(provider=provider)
        result = ai.analyze(analysis, money_flow=money_flow)

        print_ai_result(result)

        # 保存到文件
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(result)
            print(f"\n结果已保存到: {args.output}")

    except Exception as e:
        print(f"\n分析失败: {e}")
        import traceback
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(
        description="AI缠论分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 交互模式（DeepSeek）
  python -m scripts.ai_analyze

  # 交互模式（硅基流动）
  python -m scripts.ai_analyze --provider siliconflow

  # 命令行模式
  python -m scripts.ai_analyze --code 000001

  # 多周期分析并保存
  python -m scripts.ai_analyze --code 000001 --multi --output result.txt

环境变量:
  DEEPSEEK_API_KEY      DeepSeek API密钥 (获取: https://platform.deepseek.com/api_keys)
  SILICONFLOW_API_KEY   硅基流动API密钥 (获取: https://cloud.siliconflow.cn/account/ak)
        """
    )

    parser.add_argument('--code', help='股票代码（命令行模式）')
    parser.add_argument('--provider',
                        choices=['deepseek', 'siliconflow'],
                        help='AI服务提供商 (默认: deepseek)')
    parser.add_argument('--begin-date', help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--multi', action='store_true',
                        help='多周期分析（日线+周线）')
    parser.add_argument('--no-money-flow', action='store_true',
                        help='不获取资金流向数据')
    parser.add_argument('--output', help='保存分析结果到文件')

    args = parser.parse_args()

    try:
        if args.code:
            # 命令行模式
            command_mode(args)
        else:
            # 交互模式
            interactive_mode(args)

    except KeyboardInterrupt:
        print("\n\n程序已中断")


if __name__ == "__main__":
    main()
