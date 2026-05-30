#!/bin/bash
# A股数据自动更新脚本
# 建议：每个交易日 16:30 执行（A股15:00收盘，数据约15:30-16:00可用）
#
# 使用方法：
#   chmod +x /www/wwwroot/chananalyzer/scripts/auto_update.sh
#   宝塔面板 > 计划任务 > 添加Shell脚本任务

PROJECT_DIR="/www/wwwroot/chananalyzer"
VENV_DIR="$PROJECT_DIR/venv"
LOG_FILE="$PROJECT_DIR/logs/auto_update.log"

# 创建日志目录
mkdir -p "$PROJECT_DIR/logs"

# 记录开始时间
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 开始更新 =====" >> "$LOG_FILE"

# 激活虚拟环境
source "$VENV_DIR/bin/activate"

cd "$PROJECT_DIR"

# 1. 更新所有已缓存股票的K线数据
echo "$(date '+%Y-%m-%d %H:%M:%S') 开始更新K线数据..." >> "$LOG_FILE"
python -m scripts.update_data --all >> "$LOG_FILE" 2>&1
UPDATE_EXIT=$?

if [ $UPDATE_EXIT -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') K线数据更新完成" >> "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') K线数据更新异常（退出码: $UPDATE_EXIT），继续执行..." >> "$LOG_FILE"
fi

# 2. 同步股票基本信息（名称、行业、地区）
echo "$(date '+%Y-%m-%d %H:%M:%S') 开始同步股票信息..." >> "$LOG_FILE"
python -m scripts.cache_stock_info >> "$LOG_FILE" 2>&1
INFO_EXIT=$?

if [ $INFO_EXIT -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 股票信息同步完成" >> "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') 股票信息同步失败（退出码: $INFO_EXIT）" >> "$LOG_FILE"
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 全部完成 =====" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
