"""
Binance 公开行情镜像K线源 — 与 okx_source.py / tdx_source.py 平行的币侧实现

- 域名 data-api.binance.vision: 官方公开行情只读镜像,免 API key,
  大陆网络可直连(实测),无需代理——云服务器部署友好
- 单页 1000 根(远大于 OKX 的 300/100),日线/周线历史深度充足
- 时间口径(与 OKX 源完全一致,保证库内数据无缝衔接/增量混存):
    1d/1w bar 边界 = UTC 0:00(=北京 8:00),库内统一归位"北京日期 00:00";
    分钟 bar 存开始时刻(秒归零)。两源 ts 语义相同,切换源零迁移。
- 无复权: 加密货币无除权概念。
- 白名单符号沿用 OKX 风格 'BTC-USDT',请求时去掉连字符转 'BTCUSDT'。

用法:
    from ChanAnalyzer.binance_source import BinanceSource
    src = BinanceSource()
    df = src.get_klines('BTC-USDT', 'DAY', total=1000)
"""
import time as _time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests

# 库内 kl_type -> Binance interval 参数
INTERVAL_MAP = {
    "1M": "1m", "5M": "5m", "15M": "15m", "30M": "30m", "60M": "1h", "4H": "4h",
    "DAY": "1d", "WEEK": "1w",
}
# 日级及以上(时间口径需归位到北京日期 00:00)
_DAY_PLUS = ("DAY", "WEEK")

BASE = "https://data-api.binance.vision"


def _load_env_base() -> str:
    """读 .env BINANCE_BASE_URL(默认公开镜像域名),镜像不可达时可切换备用域名。"""
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line.startswith('BINANCE_BASE_URL=') and len(line) > len('BINANCE_BASE_URL='):
                val = line.split('=', 1)[1].strip().rstrip('/')
                if val.startswith('http'):
                    return val
    return BASE


class BinanceSource:
    """Binance 公开镜像K线源(REST 直连,无代理,带重试)"""

    def __init__(self):
        self._base = _load_env_base()
        self._session: Optional[requests.Session] = None

    def _sess(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            # 镜像国内可直连,不挂代理;尊重系统级环境变量缺席的默认行为
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
        """带重试的 GET(网络抖动/限频 429 兜底);失败返回 None"""
        last_msg = ""
        for i in range(retries):
            try:
                r = self._sess().get(self._base + path, params=params, timeout=20)
                if r.status_code == 200:
                    return r.json()
                last_msg = f"HTTP {r.status_code} {r.text[:80]}"
            except Exception as e:
                last_msg = f"{type(e).__name__}: {str(e)[:80]}"
            _time.sleep(1.5 * (i + 1))
        print(f"[binance_source] {path} 重试{retries}次仍失败: {last_msg} params={params}")
        return None

    # ---------- 拉取 ----------

    def get_klines(self, inst_id: str, kl_type: str, total: int = 1000) -> Optional[pd.DataFrame]:
        """
        拉K线(原始价),/api/v3/klines 分页(每页最多1000根)。

        Args:
            inst_id: 'BTC-USDT' 风格符号(自动转 BTCUSDT)
            kl_type: 库内周期 '1M'/'5M'/.../'4H'/'DAY'/'WEEK'
            total: 目标根数(日线1000≈2.7年;镜像历史深度充足,基本一两页拉满)

        Returns: DataFrame[date,open,high,low,close,volume,amount] 按时间升序;失败 None
        """
        interval = INTERVAL_MAP.get(kl_type)
        if interval is None:
            raise ValueError(f"不支持的周期: {kl_type}")
        symbol = inst_id.replace("-", "").upper()

        # 1) 最新一段(不传时间参数 = 最新 limit 根)
        rows: List[list] = list(self._get("/api/v3/klines",
                                         {"symbol": symbol, "interval": interval,
                                          "limit": min(1000, total)}) or [])
        if not rows:
            return None

        # 2) 更早历史: endTime=当前最早 openTime 向前翻(响应按 openTime 升序)
        need = total - len(rows)
        while need > 0:
            end_ts = min(int(k[0]) for k in rows)
            page = self._get("/api/v3/klines",
                             {"symbol": symbol, "interval": interval,
                              "endTime": end_ts, "limit": min(1000, need + 1)})
            if not page:
                break
            page = [k for k in page if int(k[0]) < end_ts]  # 去掉与已有重叠的 ts
            if not page:
                break
            rows = page + rows
            need = total - len(rows)

        # 去重排序(升序);字段 [openTime,o,h,l,c,vol,closeTime,quoteVol,trades,...]
        seen = {}
        for k in rows:
            seen[int(k[0])] = k
        recs = []
        for ts in sorted(seen.keys())[-total:]:
            k = seen[ts]
            dt = datetime.fromtimestamp(ts / 1000)  # UTC ms -> 北京时间
            if kl_type in _DAY_PLUS:
                # 日/周边界=UTC 0:00(北京8:00),归位到北京日期 00:00(与 OKX 源同口径)
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                dt = dt.replace(second=0, microsecond=0)
            recs.append({
                "date": dt,
                "open": float(k[1]), "high": float(k[2]),
                "low": float(k[3]), "close": float(k[4]),
                "volume": float(k[5] or 0),
                "amount": float(k[7]) if len(k) > 7 and k[7] else None,  # quote 计价成交额
            })
        return pd.DataFrame(recs)
