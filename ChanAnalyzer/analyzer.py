"""
缠论分析器 - 核心模块

封装 CChan 引擎，提供简洁的缠论分析接口

仅支持日线分析
"""
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional, Union

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE


def _load_env():
    """从 .env 文件加载环境变量"""
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())


# 在导入时加载 .env 文件
_load_env()

# 周期名称映射
KL_TYPE_NAME = {
    KL_TYPE.K_1M: "1分钟",
    KL_TYPE.K_5M: "5分钟",
    KL_TYPE.K_15M: "15分钟",
    KL_TYPE.K_30M: "30分钟",
    KL_TYPE.K_DAY: "日线",
    KL_TYPE.K_WEEK: "周线",
    KL_TYPE.K_MON: "月线",
}


class ChanAnalyzer:
    """
    缠论分析器

    使用本地缓存数据库进行日线缠论分析，输出笔、线段、中枢、买卖点等结果

    示例:
        >>> from ChanAnalyzer import ChanAnalyzer
        >>> analyzer = ChanAnalyzer(code="000001")
        >>> summary = analyzer.get_summary()
        >>> print(summary)
    """

    def __init__(
        self,
        code: str,
        begin_date: Optional[str] = None,
        end_date: Optional[str] = None,
        token: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
    ):
        """
        初始化分析器

        Args:
            code: 股票代码 (如 "000001")
            begin_date: 开始日期 (默认近5年)
            end_date: 结束日期 (默认当前)
            token: Tushare Token (默认从环境变量 TUSHARE_TOKEN 读取)
            config: 缠论配置参数
        """
        self.code = code
        self.begin_date = begin_date
        self.end_date = end_date

        # 设置 Token
        if token:
            os.environ["TUSHARE_TOKEN"] = token

        # 默认配置（MACD 默认启用）
        default_config = {
            "bi_strict": True,
            "bs_type": "1,1p,2,2s,3a,3b",
            "print_warning": False,
            "macd": {"fast": 12, "slow": 26, "signal": 9},
        }
        if config:
            default_config.update(config)
        self.config = CChanConfig(default_config)

        # 分析结果缓存
        self._chan: Optional[CChan] = None
        self._analysis: Optional[dict[str, Any]] = None

    def _get_default_begin_date(self) -> str:
        """获取默认开始日期（近5年）"""
        now = datetime.now()
        return (now - timedelta(days=1825)).strftime("%Y-%m-%d")

    def _load_chan(self) -> CChan:
        """加载缠论分析数据"""
        if self._chan is not None:
            return self._chan

        try:
            self._chan = CChan(
                code=self.code,
                begin_time=self.begin_date,
                end_time=self.end_date,
                data_src=DATA_SRC.CACHE_DB,
                lv_list=[KL_TYPE.K_DAY],
                config=self.config,
                autype=AUTYPE.QFQ,
            )
            return self._chan
        except Exception as e:
            raise RuntimeError(f"加载 {self.code} 数据失败: {e}")

    def _analyze_single_level(self, chan: CChan, level_idx: int) -> dict[str, Any]:
        """分析单个级别的数据"""
        kl_data = chan[level_idx]
        kl_type = chan.lv_list[level_idx]

        # 获取 K 线信息
        kline_count = len(kl_data.lst)
        if kline_count == 0:
            return {
                "kl_type": KL_TYPE_NAME.get(kl_type, str(kl_type)),
                "kline_count": 0,
                "error": "无K线数据",
            }

        # 获取第一根和最后一根 K 线
        first_klc = kl_data.lst[0]
        last_klc = kl_data.lst[-1]
        first_klu = first_klc.lst[0]
        last_klu = last_klc.lst[-1]
        start_date = first_klc.time_begin.to_str()
        end_date = last_klc.time_end.to_str()

        # 获取最新 K 线的 MACD 数据
        latest_macd = None
        if hasattr(last_klu, 'macd') and last_klu.macd is not None:
            latest_macd = {
                "macd": last_klu.macd.macd,
                "dif": last_klu.macd.DIF,
                "dea": last_klu.macd.DEA,
            }

        # 获取笔数据（包含 MACD）
        bi_list = []
        for bi in kl_data.bi_list:
            end_klu = bi.get_end_klu()
            bi_macd = None
            if hasattr(end_klu, 'macd') and end_klu.macd is not None:
                bi_macd = end_klu.macd.macd

            bi_list.append({
                "idx": bi.idx,
                "dir": "向上" if bi.is_up() else "向下",
                "start_date": bi.get_begin_klu().time.to_str(),
                "end_date": end_klu.time.to_str(),
                "start_price": bi.get_begin_val(),
                "end_price": bi.get_end_val(),
                "is_sure": bi.is_sure,
                "macd": bi_macd,
            })

        # 获取线段数据
        seg_list = []
        for seg in kl_data.seg_list:
            seg_list.append({
                "idx": seg.idx,
                "dir": "向上" if seg.is_up() else "向下",
                "start_date": seg.get_begin_klu().time.to_str(),
                "end_date": seg.get_end_klu().time.to_str(),
                "start_price": seg.get_begin_val(),
                "end_price": seg.get_end_val(),
                "bi_count": seg.cal_bi_cnt(),
                "is_sure": seg.is_sure,
            })

        # 获取中枢数据
        zs_list = []
        for zs in kl_data.zs_list:
            begin_klu = zs.begin_bi.get_begin_klu()
            end_klu = zs.end_bi.get_end_klu()
            zs_list.append({
                "idx": zs.begin_bi.idx,
                "start_date": begin_klu.time.to_str(),
                "end_date": end_klu.time.to_str(),
                "high": zs.high,
                "low": zs.low,
                "center": zs.mid,
                "bi_count": zs.end_bi.idx - zs.begin_bi.idx + 1,
            })

        # 获取买卖点数据
        buy_signals = []
        sell_signals = []
        for bsp in kl_data.bs_point_lst.bsp_iter():
            signal = {
                "type": bsp.type2str(),
                "type_raw": bsp.type,
                "is_buy": bsp.is_buy,
                "date": bsp.klu.time.to_str(),
                "price": bsp.klu.close,
                "klu_idx": bsp.klu.idx,
            }
            if bsp.is_buy:
                buy_signals.append(signal)
            else:
                sell_signals.append(signal)

        # 成交量分析
        volume_analysis = self._analyze_volume(kl_data)

        # K线高低点统计
        kline_range = self._analyze_kline_range(kl_data)

        # 中枢位置判断
        zs_position = self._get_zs_position(last_klu.close, zs_list)

        # 最新状态
        current_price = last_klu.close
        latest_bi = bi_list[-1] if bi_list else None
        latest_seg = seg_list[-1] if seg_list else None
        latest_zs = zs_list[-1] if zs_list else None

        return {
            "kl_type": KL_TYPE_NAME.get(kl_type, str(kl_type)),
            "kl_type_enum": kl_type,
            "start_date": start_date,
            "end_date": end_date,
            "kline_count": kline_count,
            "current_price": current_price,
            "macd": latest_macd,
            "bi_list": bi_list,
            "seg_list": seg_list,
            "zs_list": zs_list,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "volume_analysis": volume_analysis,
            "kline_range": kline_range,
            "zs_position": zs_position,
            "latest": {
                "bi": latest_bi,
                "seg": latest_seg,
                "zs": latest_zs,
            },
        }

    def _analyze_volume(self, kl_data) -> dict[str, Any]:
        """分析成交量数据"""
        if len(kl_data.lst) < 5:
            return {"status": "数据不足"}

        # 获取最近5根K线的成交量
        recent_klc = kl_data.lst[-5:]
        volumes = []
        price_changes = []

        for klc in recent_klc:
            # 从 trade_info.metric 获取成交量
            klc_volume = sum(
                klu.trade_info.metric.get("volume", 0) or 0
                for klu in klc.lst
            )
            klc_close = klc.lst[-1].close
            klc_open = klc.lst[0].open
            volumes.append(klc_volume)
            price_changes.append(klc_close > klc_open)

        current_vol = volumes[-1]
        avg_vol = sum(volumes) / len(volumes)
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1

        # 量能状态判断
        if vol_ratio < 0.5:
            vol_status = "缩量（<0.5倍均量）"
        elif vol_ratio > 2:
            vol_status = "放量（>2倍均量）"
        else:
            vol_status = "正常"

        # 最近5根K线量价分析
        k_vol_price = []
        for i in range(len(recent_klc)):
            klc = recent_klc[i]
            klc_close = klc.lst[-1].close
            klc_open = klc.lst[0].open
            klc_volume = sum(
                klu.trade_info.metric.get("volume", 0) or 0
                for klu in klc.lst
            )
            price_up = klc_close > klc_open
            vol_high = klc_volume > avg_vol
            k_vol_price.append({
                "price_up": price_up,
                "vol_high": vol_high,
                "desc": "价格涨, 放量" if price_up and vol_high else
                       "价格涨, 缩量" if price_up and not vol_high else
                       "价格跌, 放量" if not price_up and vol_high else
                       "价格跌, 缩量"
            })

        # 量价配合判断
        recent_price_up = sum(1 for kvp in k_vol_price[-3:] if kvp["price_up"])
        if recent_price_up >= 2:
            price_trend = "上涨"
            recent_vol_high = sum(1 for kvp in k_vol_price[-3:] if kvp["vol_high"])
            if recent_vol_high >= 2:
                vol_price_rel = "价涨量增（健康上涨）"
            else:
                vol_price_rel = "价涨量缩（上涨乏力）"
        else:
            price_trend = "下跌/震荡"
            recent_vol_high = sum(1 for kvp in k_vol_price[-3:] if kvp["vol_high"])
            if recent_vol_high >= 2:
                vol_price_rel = "价跌量增（恐慌抛售）"
            else:
                vol_price_rel = "价跌量缩（惜售）"

        return {
            "current_vol": current_vol,
            "avg_vol": avg_vol,
            "vol_ratio": vol_ratio,
            "vol_status": vol_status,
            "k_vol_price": k_vol_price,
            "vol_price_rel": vol_price_rel,
        }

    def _analyze_kline_range(self, kl_data, period: int = 20) -> dict[str, Any]:
        """提取近期K线高低点统计

        Args:
            kl_data: K线数据
            period: 统计周期（默认20根K线）
        """
        total = len(kl_data.lst)
        if total == 0:
            return {"status": "无K线数据"}

        take = min(period, total)
        recent = kl_data.lst[-take:]

        highs = []
        lows = []
        closes = []
        for klc in recent:
            klu_high = max(klu.high for klu in klc.lst)
            klu_low = min(klu.low for klu in klc.lst)
            highs.append(klu_high)
            lows.append(klu_low)
            closes.append(klc.lst[-1].close)

        period_high = max(highs)
        period_low = min(lows)
        current_price = closes[-1]

        # 当前价格在区间内的位置百分比
        range_width = period_high - period_low
        if range_width > 0:
            position_pct = (current_price - period_low) / range_width * 100
        else:
            position_pct = 50.0

        # 距高低点的幅度
        dist_high_pct = (current_price - period_high) / period_high * 100 if period_high > 0 else 0
        dist_low_pct = (current_price - period_low) / period_low * 100 if period_low > 0 else 0

        return {
            "period": take,
            "period_high": round(period_high, 2),
            "period_low": round(period_low, 2),
            "current_price": round(current_price, 2),
            "position_pct": round(position_pct, 1),
            "dist_high_pct": round(dist_high_pct, 2),
            "dist_low_pct": round(dist_low_pct, 2),
        }

    def _get_zs_position(self, price: float, zs_list: list) -> str:
        """判断价格相对中枢的位置"""
        if not zs_list:
            return "无中枢"

        latest_zs = zs_list[-1]
        if price > latest_zs['high']:
            return "中枢上方（强势）"
        elif price < latest_zs['low']:
            return "中枢下方（弱势）"
        else:
            return "中枢内部"

    def get_analysis(self) -> dict[str, Any]:
        """
        获取结构化分析结果

        Returns:
            日线分析结果字典
        """
        if self._analysis is not None:
            return self._analysis

        chan = self._load_chan()

        self._analysis = self._analyze_single_level(chan, 0)
        self._analysis["code"] = self.code
        self._analysis["name"] = self.code

        return self._analysis

    def get_bs_points(self) -> list[dict[str, Any]]:
        """
        获取买卖点列表

        Returns:
            买卖点列表
        """
        analysis = self.get_analysis()
        return analysis.get("buy_signals", []) + analysis.get("sell_signals", [])

    def get_summary(self) -> str:
        """
        获取文本摘要

        Returns:
            格式化的分析报告文本
        """
        from ChanAnalyzer.formatter import format_summary

        analysis = self.get_analysis()
        if "error" in analysis:
            return f"分析失败: {analysis['error']}"

        return format_summary(analysis)
