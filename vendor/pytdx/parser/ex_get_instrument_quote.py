# coding=utf-8

from pytdx.parser.base import BaseParser
from pytdx.helper import get_datetime, get_volume, get_price
from collections import OrderedDict
import struct

# bytearray(b'TDX_DS\x00\x00\x00\x00\x00\x1f\xdc\x00\x00\x01\x00\x00\x00=\x9c\x00\x00t\x00\x00\x00\x00\x00\x00\x00')


"""
tradex result:

﻿
市场    代码    昨收    开盘    最高    最低    现价    开仓    持仓    总量
现量    内盘    外盘    买一价  买二价  买三价  买四价  买五价  买一量  买二量
买三量  买四量  买五量  卖一价  卖二价  卖三价  卖四价  卖五价  卖一量  卖二量
卖三量  卖四量  卖五量  仓差    日期
47      IF1709  3718.199951     3717.199951     3724.000000     3696.600098
3703.000000     2043    13340   1728    3       869     859     3702.800049
0.000000        0.000000        0.000000        0.000000        1       0
0       0       0       3704.399902     0.000000        0.000000        0.000000
        0.000000        1       0       0       0       0       13025   20170721

"""
class GetInstrumentQuote(BaseParser):
    at1 = 0
    def setParams(self, market, code):
        # pkg = bytearray.fromhex("01 01 08 02 02 01 0c 00 0c 00 fa 23")
        pkg = bytearray.fromhex("01 01 00 29 00 01 0e 00  0e 00 fb 23 01 00")
        pkg.extend(struct.pack('<B', market))
        code = code.encode("utf-8")
        pkg.extend(struct.pack('<9s', code))

        self.send_pkg = pkg

    def parseResponse(self, body_buf):


        if (len(body_buf) < 20):
            return []

        pos = 0
        # market, code = struct.unpack('<B9s', body_buf[pos: pos+10])
        market,_, code = struct.unpack('<BH9s', body_buf[pos: pos+12])
        pos += 12

        # jump 4
        pos += 4

        ## 持仓 ((13340,), 66),

        (pre_close, open_price, high, low, price, kaicang, _,
         zongliang, xianliang, _ , neipan, waipai,
         _, chicang,
         b1, b2, b3, b4, b5,
         bv1, bv2, bv3, bv4, bv5,
         a1, a2, a3, a4, a5,
         av1, av2, av3, av4, av5
         ) = struct.unpack('<5f9I5f5I5f5I', body_buf[pos: pos+136])


        return [
            OrderedDict(
                [
                    ('market', market),
                    ('code', code.decode("utf-8").rstrip('\x00')),
                    ('pre_close', pre_close),
                    ('open', open_price),
                    ('high', high),
                    ('low', low),
                    ('price', price),
                    ('kaicang', kaicang),
                    ('zongliang', zongliang),
                    ('xianliang', xianliang),
                    ('neipan', neipan),
                    ('waipan', waipai),
                    ('chicang', chicang),
                    ('bid1', b1),
                    ('bid2', b2),
                    ('bid3', b3),
                    ('bid4', b4),
                    ('bid5', b5),
                    ('bid_vol1', bv1),
                    ('bid_vol2', bv2),
                    ('bid_vol3', bv3),
                    ('bid_vol4', bv4),
                    ('bid_vol5', bv5),
                    ('ask1', a1),
                    ('ask2', a2),
                    ('ask3', a3),
                    ('ask4', a4),
                    ('ask5', a5),
                    ('ask_vol1', av1),
                    ('ask_vol2', av2),
                    ('ask_vol3', av3),
                    ('ask_vol4', av4),
                    ('ask_vol5', av5),
                ]
            )
        ]


if __name__ == '__main__':
    from pytdx.exhq import TdxExHq_API

    api = TdxExHq_API()
    with api.connect('61.152.107.141', 7727):
        print(api.to_df(api.get_instrument_quote(47, "IF1709")))



