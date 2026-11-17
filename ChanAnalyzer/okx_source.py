"""
OKX 加密货币K线数据源(REST 直连) — 与 tdx_source.py 平行的币侧实现

- 放弃 ccxt: 其符号解析依赖 load_markets 的 1.3MB instruments 响应,
  经 Clash 代理高概率 SSL EOF 中断(实测);而 candles 接口(几KB)稳定。
  我们只用 OKX 原生 instId(如 BTC-USDT),不需要统一符号层。
- 代理必选: OKX API 大陆不可直连,走 Clash HTTP 代理(.env OKX_PROXY,默认 7897)
- 分页: /market/candles(最新300根) + /market/history-candles(向前翻,每页100根)
- 时间口径(关键约定):
    OKX 的 1D/1W bar 边界是 UTC 0:00(=北京 8:00)。库内统一存"北京日期 00:00",
    使缠论标记(klu.time,日线约定 0:00)与 TV bars(读库内 date)完全自洽,
    否则笔/中枢会与K线错位 8 小时。
    分钟 bar 存开始时刻(秒归零),与 A 股分钟口径一致。
- 无复权: 加密货币无除权,qfq 整条链不适用。

用法:
    from ChanAnalyzer.okx_source import OkxSource
    src = OkxSource()
    df = src.get_klines('BTC-USDT', 'DAY', total=1000)
"""
import time as _time
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests

# 库内 kl_type -> OKX bar 参数(注意大写 H/D/W 是 OKX 规范)
BAR_MAP = {
    "1M": "1m", "5M": "5m", "15M": "15m", "30M": "30m", "60M": "1H", "4H": "4H",
    "DAY": "1D", "WEEK": "1W",
}
# 周期分钟数(分页缺口估算用)
PERIOD_MIN = {"1M": 1, "5M": 5, "15M": 15, "30M": 30, "60M": 60, "4H": 240,
              "DAY": 1440, "WEEK": 10080}
# 日级及以上(时间口径需归位到北京日期 00:00)
_DAY_PLUS = ("DAY", "WEEK")

BASE = "https://www.okx.com"


def _load_env_base() -> str:
    """读 .env OKX_BASE_URL(默认主域名)。
    大陆环境主域名被 DNS 污染(解析到 169.254.0.2 黑洞)时,
    可配 OKX_BASE_URL=https://aws.okx.com (OKX 官方备用出海线路)。"""
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line.startswith('OKX_BASE_URL=') and len(line) > len('OKX_BASE_URL='):
                val = line.split('=', 1)[1].strip().rstrip('/')
                if val.startswith('http'):
                    return val
    return BASE


def _load_env_proxy() -> Optional[str]:
    """读 .env OKX_PROXY:
    - none/direct/off (不区分大小写) -> 返回 None,直连(海外服务器)
    - 未配置 -> 默认 Clash 7897(本机大陆环境兼容;云服务器务必显式配置)
    - 其他值 -> 该代理地址(国内服务器自建代理)
    """
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line.startswith('OKX_PROXY=') and len(line) > len('OKX_PROXY='):
                val = line.split('=', 1)[1].strip()
                return None if val.lower() in ("none", "direct", "off") else val
    return "http://127.0.0.1:7897"  # Clash 默认混合端口


class OkxSource:
    """OKX K线源(REST 直连 + Clash 代理,带重试)"""

    def __init__(self, proxy: Optional[str] = None):
        self._proxy = proxy if proxy is not None else _load_env_proxy()
        self._base = _load_env_base()
        self._session: Optional[requests.Session] = None

    def _sess(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            if self._proxy:
                s.proxies = {"http": self._proxy, "https": self._proxy}
            s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) chananalyzer"
            self._session = s
        return self._session

    def close(self):
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

    def _get(self, path: str, params: dict, retries: int = 4) -> Optional[list]:
        """带重试的 GET(代理抖动/OKX限频兜底);失败返回 None"""
        last_msg = ""
        for i in range(retries):
            try:
                r = self._sess().get(self._base + path, params=params, timeout=20)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("code") == "0":
                        return data.get("data", [])
                    last_msg = f"okx code={data.get('code')} {data.get('msg', '')[:60]}"
                else:
                    last_msg = f"HTTP {r.status_code}"
            except Exception as e:
                last_msg = f"{type(e).__name__}: {str(e)[:80]}"
            _time.sleep(1.5 * (i + 1))
        print(f"[okx_source] {path} 重试{retries}次仍失败: {last_msg} params={params}")
        return None

    # ---------- 拉取 ----------

    def get_klines(self, inst_id: str, kl_type: str, total: int = 1000) -> Optional[pd.DataFrame]:
        """
        拉K线(原始价,无复权概念),candles + history-candles 分页。

        Args:
            inst_id: OKX 产品ID,如 'BTC-USDT'(现货)
            kl_type: 库内周期 '5M'/'15M'/'30M'/'60M'/'DAY'/'WEEK'
            total: 目标根数(日线1000≈2.7年,分钟1000≈3.5天@5m)

        Returns: DataFrame[date,open,high,low,close,volume,amount] 按时间升序;失败 None
        """
        bar = BAR_MAP.get(kl_type)
        if bar is None:
            raise ValueError(f"不支持的周期: {kl_type}")

        # 1) 最新一段: /market/candles 单页最多 300
        latest = self._get("/api/v5/market/candles",
                           {"instId": inst_id, "bar": bar, "limit": min(300, total)})
        if latest is None:
            return None
        rows: List[list] = list(latest)

        # 2) 更早历史: /market/history-candles 每页 100,after=当前最早ts 向前翻
        #    注意 OKX 数组按 ts 倒序(新->旧),锚点取 min(ts)
        need = total - len(rows)
        while need > 0 and rows:
            after = min(int(r[0]) for r in rows)
            page = self._get("/api/v5/market/history-candles",
                             {"instId": inst_id, "bar": bar, "after": after, "limit": 100})
            if not page:
                break
            # 跳过与已有重复/重叠的 ts
            page = [p for p in page if int(p[0]) < after]
            if not page:
                break
            rows = page + rows
            need = total - len(rows)

        if not rows:
            return None

        # 去重排序(ts 升序);字段 [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
        from datetime import datetime
        seen = {}
        for r in rows:
            seen[int(r[0])] = r
        recs = []
        for ts in sorted(seen.keys())[-total:]:
            r = seen[ts]
            dt = datetime.fromtimestamp(ts / 1000)  # UTC ms -> 北京时间
            if kl_type in _DAY_PLUS:
                # OKX 日/周边界=UTC 0:00(北京8:00),归位到北京日期 00:00
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                dt = dt.replace(second=0, microsecond=0)
            recs.append({
                "date": dt,
                "open": float(r[1]), "high": float(r[2]),
                "low": float(r[3]), "close": float(r[4]),
                "volume": float(r[5] or 0), "amount": None,
            })
        return pd.DataFrame(recs)
