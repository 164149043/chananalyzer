"""
缓存股票基本信息到数据库

将股票代码、名称、行业、地区等信息存储到 chan.db 的 stock_info 表中
"""
import os
import sys
import sqlite3
from pathlib import Path

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chan.db")

# ==================== 修复 tushare 权限问题 ====================
os.environ['TUSHARE_PATH'] = '/tmp'

import pandas as pd
import tushare as ts

_original_set_token = ts.set_token
_original_pro_api = ts.pro_api

def _patched_set_token(token):
    fp = '/tmp/tk.csv'
    if os.path.exists(fp):
        try:
            os.remove(fp)
        except:
            pass
    df = pd.DataFrame({'token': [token]})
    df.to_csv(fp, index=False)
    ts._Tushare__token = token

def _patched_pro_api(token=None):
    if token:
        return _original_pro_api(token=token)
    fp = '/tmp/tk.csv'
    if os.path.exists(fp):
        df = pd.read_csv(fp)
        token = df['token'][0]
        return _original_pro_api(token=token)
    return _original_pro_api()

ts.set_token = _patched_set_token
ts.pro_api = _patched_pro_api
# ==================== 修复结束 ====================


def get_tushare_token():
    """获取 Tushare Token"""
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        # 尝试从 .env 文件读取
        env_path = Path(os.path.dirname(DB_PATH)) / '.env'
        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        if key.strip() == 'TUSHARE_TOKEN':
                            token = value.strip()
                            break
    return token


def fetch_stock_info_from_tushare():
    """从 Tushare 获取所有股票基本信息"""
    token = get_tushare_token()
    if not token:
        print("错误: 未设置 TUSHARE_TOKEN 环境变量")
        print("请在 .env 文件中配置: TUSHARE_TOKEN=your_token")
        return []

    try:
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()

        print("正在从 Tushare 获取股票基本信息...")
        df = pro.stock_basic(
            exchange='',
            list_status='L',
            fields='ts_code,symbol,name,industry,area'
        )

        if df is None or df.empty:
            print("未获取到数据")
            return []

        # 保留沪深北交易所股票
        df = df[(df['ts_code'].str.endswith('.SZ')) | (df['ts_code'].str.endswith('.SH')) | (df['ts_code'].str.endswith('.BJ'))]

        result = []
        for _, row in df.iterrows():
            ts_code = row['ts_code']
            code = ts_code.split('.')[0]
            result.append({
                'code': code,
                'name': row['name'],
                'industry': row.get('industry', ''),
                'area': row.get('area', '')
            })

        print(f"从 Tushare 获取到 {len(result)} 只股票信息")
        return result

    except Exception as e:
        print(f"从 Tushare 获取股票信息失败: {e}")
        return []


def save_stock_info_to_db(stock_info_list):
    """保存股票信息到数据库"""
    if not stock_info_list:
        print("没有数据需要保存")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 清空旧数据
        cursor.execute('DELETE FROM stock_info')

        # 批量插入
        for info in stock_info_list:
            cursor.execute('''
                INSERT OR REPLACE INTO stock_info (code, name, industry, area)
                VALUES (?, ?, ?, ?)
            ''', (info['code'], info['name'], info['industry'], info['area']))

        conn.commit()
        print(f"已保存 {len(stock_info_list)} 条股票信息到数据库")

        # 验证
        cursor.execute('SELECT COUNT(*) FROM stock_info')
        count = cursor.fetchone()[0]
        print(f"数据库中共有 {count} 条股票信息")

    except Exception as e:
        conn.rollback()
        print(f"保存失败: {e}")
    finally:
        conn.close()


def get_stock_info_from_db():
    """从数据库获取股票信息"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT code, name, industry, area FROM stock_info')
        rows = cursor.fetchall()
        return {row[0]: {'name': row[1], 'industry': row[2], 'area': row[3]} for row in rows}
    finally:
        conn.close()


def main():
    """主函数"""
    print("=" * 60)
    print("股票信息缓存工具")
    print("=" * 60)

    # 检查数据库
    if not os.path.exists(DB_PATH):
        print(f"错误: 数据库文件不存在: {DB_PATH}")
        return

    # 检查表是否存在
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='stock_info'
    ''')
    if not cursor.fetchone():
        # 创建表
        cursor.execute('''
            CREATE TABLE stock_info (
                code TEXT PRIMARY KEY,
                name TEXT,
                industry TEXT,
                area TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        print("已创建 stock_info 表")
    conn.close()

    # 获取并保存股票信息
    stock_info_list = fetch_stock_info_from_tushare()
    if stock_info_list:
        save_stock_info_to_db(stock_info_list)
        print("\n股票信息缓存完成!")
    else:
        print("\n未能获取股票信息，请检查 TUSHARE_TOKEN 配置")


if __name__ == "__main__":
    main()
