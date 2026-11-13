# coding=utf-8

from pytdx.parser.base import BaseParser
from pytdx.helper import get_datetime, get_volume, get_price
from collections import OrderedDict
import struct


class ExSetupCmd1(BaseParser):

    def setup(self):
        self.send_pkg = bytearray.fromhex("01 01 48 65 00 01 52 00 52 00 54 24 fc f0 0e 92"
                                          "f3 c8 37 83 1f 32 c6 e5 d5 3d fb 41 cd 9c f2 07"
                                          "fc d0 3c f6 f2 f7 a4 77 47 83 1d 59 2b 30 72 43"
                                          "51 c7 e0 41 d4 0e c0 d8 c8 a0 76 be 1f 32 c6 e5"
                                          "d5 3d fb 41 1f 32 c6 e5 d5 3d fb 41 f3 43 87 e6"
                                          "68 a9 2a a3 70 11 e4 9c d2 6e b0 1a")       
        # self.send_pkg = bytearray.fromhex("01 01 48 65 00 01 52 00 52 00 54 24 1f 32 c6 e5"
        #                                     "d5 3d fb 41 1f 32 c6 e5 d5 3d fb 41 1f 32 c6 e5"
        #                                     "d5 3d fb 41 1f 32 c6 e5 d5 3d fb 41 1f 32 c6 e5"
        #                                     "d5 3d fb 41 1f 32 c6 e5 d5 3d fb 41 1f 32 c6 e5"
        #                                     "d5 3d fb 41 1f 32 c6 e5 d5 3d fb 41 cc e1 6d ff"
        #                                     "d5 ba 3f b8 cb c5 7a 05 4f 77 48 ea")

    def parseResponse(self, body_buf):
        pass