"""
通达信(tdx)K线数据源 — 自包含模块,不依赖 chanlun 项目

- vendor/pytdx(GBK修复版)为本项目内置依赖,导入时自动加入 sys.path 优先级最高
- 服务器连接:内置常用列表,首个"连接+查询"成功的即用,失败自动换下一个
- 日线:分页拉取(700根/页)原始价,合并去重
- 复权:移植 chanlun-pro klines_fq 的精确前复权算法(手工验算事件基准价通过,2026-11)
    category=1  除权除息(分红/转增/配股): preclose 逐日因子 + 反向累积
    category=11 扩缩股: 事件日之前 价格/=suogu, 成交量*=suogu
    自愈:重整转增等特殊除权实际基准与标准公式不符 → 事件日跳空超板块物理上限时回退重算

用法:
    from ChanAnalyzer.tdx_source import TdxSource
    src = TdxSource()
    df = src.get_daily_qfq('000001')   # DataFrame[date,open,high,low,close,volume,amount]
"""
import sys
import time
from pathlib import Path
from typing import List, Optional

import pandas as pd

# vendor/pytdx 修复版优先于任何 pip 安装版本
_VENDOR = Path(__file__).parent.parent / "vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from pytdx.hq import TdxHq_API  # noqa: E402

# 常用行情服务器
# 域名优先:本机 Clash 代理环境下,裸 IP 的 TCP 会被分流到代理节点导致查询挂起/失败,
# 域名命中 Clash 直连规则才能正常通信(sztdx.gtjas.com 为 chan-analyse 选优缓存实测可用)
TDX_SERVERS = [
    ("sztdx.gtjas.com", 7709),  # 国泰君安深圳(实测可用,域名直连)
    ("119.147.212.81", 7709),   # 招商证券深圳
    ("115.238.90.165", 7709),   # 杭州电信主站J4
    ("218.108.98.244", 7709),   # 杭州华数主站J1
    ("180.153.18.170", 7709),   # 上海电信主站Z1
    ("123.125.108.14", 7709),   # 上证云北京联通
    ("218.6.170.47", 7709),     # 上证云成都电信
    ("114.80.63.12", 7709),     # 云行情上海电信
    ("14.17.75.71", 7709),      # 深圳电信主站
    ("221.231.141.60", 7709),   # 华泰证券南京
]

CATEGORY_DAY = 9  # pytdx 日线 category


def _to_market_code(code: str):
    """'000001' -> (0=SZ, '000001'); '600519' -> (1=SH, '600519')"""
    code = code.strip()
    if code.startswith(("6",)):
        return 1, code
    return 0, code


class TdxSource:
    """通达信日线数据源(带连接管理与前复权)"""

    def __init__(self):
        self._api: Optional[TdxHq_API] = None
        self._server_idx = 0

    # ---------- 连接管理 ----------

    def _connect(self) -> TdxHq_API:
        """获取可用连接:已连接直接用;否则遍历服务器列表直到"连接+试查询"成功"""
        if self._api is not None:
            return self._api
        last_err = None
        for i in range(len(TDX_SERVERS)):
            host, port = TDX_SERVERS[(self._server_idx + i) % len(TDX_SERVERS)]
            # raise_exception=True: 查询失败显式抛异常,避免静默 None 导致在同个坏连接上重试
            api = TdxHq_API(raise_exception=True, auto_retry=True)
            try:
                if not api.connect(host, port, time_out=8):
                    continue
                # 连接成功后做一次真实查询验证(部分服务器 TCP 通但业务不响应)
                if api.get_security_bars(CATEGORY_DAY, 0, "000001", 0, 5):
                    self._api = api
                    self._server_idx = (self._server_idx + i) % len(TDX_SERVERS)
                    return api
                api.disconnect()
            except Exception as e:
                last_err = e
                try:
                    api.disconnect()
                except Exception:
                    pass
        raise ConnectionError(f"所有通达信服务器不可用,最后错误: {last_err}")

    def _reset(self):
        """断开当前连接,下次调用换下一个服务器"""
        if self._api is not None:
            try:
                self._api.disconnect()
            except Exception:
                pass
        self._api = None
        self._server_idx = (self._server_idx + 1) % len(TDX_SERVERS)

    def close(self):
        if self._api is not None:
            try:
                self._api.disconnect()
            except Exception:
                pass
            self._api = None

    # ---------- 数据拉取 ----------

    def _bars_with_retry(self, category: int, market: int, code: str,
                         start: int, count: int, retries: int = 4):
        """带重试+换服务器的K线查询(返回 DataFrame 或 None)"""
        for attempt in range(retries):
            try:
                api = self._connect()
                res = api.get_security_bars(category, market, code, start, count)
                if res:
                    return api.to_df(res)  # raise_exception 模式返回 list,需转 DataFrame
            except Exception:
                self._reset()
            time.sleep(0.5 * (attempt + 1))
        return None

    def get_daily_raw(self, code: str, pages: int = 8) -> Optional[pd.DataFrame]:
        """
        拉原始(不复权)日线,分页 700 根/页,默认 8 页 ≈ 5600 根(约23年)

        Returns: DataFrame[date(datetime),open,high,low,close,volume,amount] 按日期升序;失败 None
        """
        market, tcode = _to_market_code(code)
        frames: List[pd.DataFrame] = []
        for i in range(pages):
            df = self._bars_with_retry(CATEGORY_DAY, market, tcode, i * 700, 700)
            if df is None or len(df) == 0:
                break
            frames.append(df)
            if len(df) < 700:
                break
        if not frames:
            return None
        ks = pd.concat(frames, axis=0, sort=False)
        ks = ks.drop_duplicates(["datetime"], keep="last").sort_values("datetime")
        ks = ks.rename(columns={"vol": "volume"})
        ks["date"] = pd.to_datetime(ks["datetime"])
        return ks[["date", "open", "close", "high", "low", "volume", "amount"]].reset_index(drop=True)

    def get_xdxr(self, code: str) -> pd.DataFrame:
        """拉除权除息事件表(原始全部事件)"""
        market, tcode = _to_market_code(code)
        for attempt in range(3):
            try:
                api = self._connect()
                data = api.get_xdxr_info(market, tcode)
                if data is not None:
                    df = pd.DataFrame(data)
                    if len(df) == 0:
                        return df
                    df["date"] = pd.to_datetime(
                        df[["year", "month", "day"]].astype(int).astype(str).agg("-".join, axis=1)
                    )
                    return df
            except Exception:
                self._reset()
            time.sleep(0.5 * (attempt + 1))
        return pd.DataFrame()

    # ---------- 前复权(精确口径,手工验算事件基准价通过;含特殊除权自愈) ----------

    @staticmethod
    def qfq_adjust(df: pd.DataFrame, xdxr: pd.DataFrame) -> pd.DataFrame:
        """
        精确前复权(最新价为真实市价):
        - cat=11 扩缩股: 事件日之前 价格/=suogu, 成交量*=suogu
        - cat=1 除权除息: preclose 逐日公式 + 因子反向累积
        - 自愈: 重整转增等特殊除权的实际基准与标准公式不符,标准复权后事件日
          跳空会超板块物理上限(主板11%/创业科创21%,留1%余量) → 回退该事件重算。
          只检查事件日,停牌复牌/新股初期无限制行情不受影响。
        """
        if df is None or len(df) == 0:
            return df
        df = df.copy()
        if xdxr is None or len(xdxr) == 0:
            return df

        # 1) 扩缩股
        for _, row in xdxr[xdxr["category"] == 11].iterrows():
            sg = row.get("suogu", 0)
            if not sg or sg <= 0:
                continue
            mask = df["date"] < row["date"]
            for col in ("open", "high", "low", "close"):
                df.loc[mask, col] = df.loc[mask, col] / sg
            df.loc[mask, "volume"] = df.loc[mask, "volume"] * sg

        # 2) 除权除息:事件值精确对齐到事件日K线(除权日必为交易日),非事件日补0
        ev = xdxr[xdxr["category"] == 1][["date", "fenhong", "peigu", "peigujia", "songzhuangu"]].copy()
        if len(ev) == 0:
            return df
        # 粒度对齐:K线date带15:00时分、事件date为00:00,不归一则merge永远匹配不上
        # (2026-11重播种事故:5012只全部漏复权,除权日残留-28%原始除权缺口)
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        ev["date"] = pd.to_datetime(ev["date"]).dt.normalize()

        # 板块涨跌停物理上限(留1%余量),用于自愈检测;代码经 df.attrs 传入
        limit = 0.21 if str(df.attrs.get("code", "")).startswith(("30", "68")) else 0.11

        def _apply(ev_df: pd.DataFrame) -> pd.DataFrame:
            m = df.merge(ev_df, on="date", how="left")
            for col in ("fenhong", "peigu", "peigujia", "songzhuangu"):
                m[col] = m[col].fillna(0)
            # 逐日前收盘:非事件日 = 昨收;事件日 = 除权基准价
            m["preclose"] = (
                m["close"].shift(1) * 10 - m["fenhong"] + m["peigu"] * m["peigujia"]
            ) / (10 + m["peigu"] + m["songzhuangu"])
            # 前复权因子:从最新往最早累积
            m["adj"] = (m["preclose"].shift(-1) / m["close"]).fillna(1)[::-1].cumprod()
            for col in ("open", "high", "low", "close"):
                m[col] = (m[col] * m["adj"]).round(3)
            return m.reset_index(drop=True)

        m = _apply(ev)

        # 3) 自愈循环:回退"标准复权后事件日跳空超物理上限"的特殊事件,重算
        for _ in range(4):
            ev_days = set(ev["date"])
            prev_c = m["close"].shift(1)
            bad = [
                row["date"]
                for idx, row in m.iterrows()
                if row["date"] in ev_days
                and pd.notna(prev_c[idx])
                and prev_c[idx] > 0
                and abs(row["open"] / prev_c[idx] - 1) > limit
            ]
            if not bad:
                break
            mask = ev["date"].isin(bad)
            for col in ("fenhong", "peigu", "peigujia", "songzhuangu"):
                ev.loc[mask, col] = 0.0
            m = _apply(ev)

        return m[["date", "open", "high", "low", "close", "volume", "amount"]]

    def get_daily_qfq(self, code: str, pages: int = 8) -> Optional[pd.DataFrame]:
        """拉前复权日线(组合接口,生产用这个)"""
        raw = self.get_daily_raw(code, pages)
        if raw is None:
            return None
        raw.attrs["code"] = code  # 传递股票代码给 qfq_adjust 判定板块涨跌停上限
        return self.qfq_adjust(raw, self.get_xdxr(code))
