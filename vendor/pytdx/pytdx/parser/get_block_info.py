# coding=utf-8

from pytdx.parser.base import BaseParser
from pytdx.reader.block_reader import BlockReader,BlockReader_TYPE_FLAT
from pytdx.helper import get_datetime, get_volume, get_price
from collections import OrderedDict
import struct
import six


blocklist=("block_fg.dat","block_zs.dat","block_gn.dat","block.dat")
class GetBlockInfoMeta(BaseParser):
    def setParams(self, block_file):
        block_file = block_file if block_file in blocklist else 'zhb.zip' 
        if type(block_file) is six.text_type:
            block_file = block_file.encode("utf-8")

        pkg = bytearray.fromhex(u'00 00 00 00 00 00 2a 00 2a 00 c5 02')
        # pkg = bytearray.fromhex(u'0C 39 18 69 00 01 2A 00 2A 00 C5 02')
        pkg.extend(struct.pack(u"<{}s".format(0x2a - 2), block_file))
        self.send_pkg = pkg


    def parseResponse(self, body_buf):
        (size, _, hash_value, _ ) = struct.unpack(u"<I1s32s1s", body_buf)
        
        return {
            "size": size,
            "hash_value" : hash_value
        }

class GetBlockInfo(BaseParser):

    def setParams(self, block_file, start, size):
        block_file = block_file if block_file in blocklist else 'zhb.zip' 
        if type(block_file) is six.text_type:
            block_file = block_file.encode("utf-8")
        pkg = bytearray.fromhex(u'0c 37 18 6a 00 01 6e 00 6e 00 b9 06')
        #pkg = bytearray.fromhex(u'0c 33 18 6a 00 01 6e 00 6e 00 b9 06 60 ea 00 00 30 75 00 00')
        pkg.extend(struct.pack(u"<II{}s".format(0x6e-10), start, size, block_file))
        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        return body_buf[4:]

def get_block_dat_ver_up(client, blockfile):
    try:
        meta = client.get_block_info_meta(blockfile)
    except Exception as e:
        return None

    if not meta:
        return None

    size = meta['size']
    one_chunk = 0x7530
    # one_chunk = 0x2000

    chuncks = size // one_chunk
    if size % one_chunk != 0:
        chuncks += 1

    file_content = bytearray()
    for seg in range(chuncks):
        start = seg * one_chunk
        piece_data = client.get_block_info(blockfile, start, size)
        file_content.extend(piece_data)  
  
    return BlockReader().get_datae(file_content,blockfile)  

def get_and_parse_block_info(client, blockfile):
    try:
        meta = client.get_block_info_meta(blockfile)
    except Exception as e:
        return None

    if not meta:
        return None

    size = meta['size']
    one_chunk = 0x7530
    # one_chunk = 0x2000


    chuncks = size // one_chunk
    if size % one_chunk != 0:
        chuncks += 1

    file_content = bytearray()
    for seg in range(chuncks):
        start = seg * one_chunk
        piece_data = client.get_block_info(blockfile, start, size)
        file_content.extend(piece_data)
    # return BlockReader().get_data(file_content,blockfile,1)
    return BlockReader().get_data(file_content,blockfile,BlockReader_TYPE_FLAT)



if __name__ == '__main__':
    from pytdx.hq import TdxHq_API
    api = TdxHq_API(auto_retry=True,heartbeat=True)
    with api.connect('39.98.234.173',7709):
        # ret = api.get_block_info("block_zs.dat", 0, 100)
        # print(len(ret))
        # ret = api.get_and_parse_block_info("block_fg.dat")
        # ret = api.get_and_parse_block_info("block_zs.dat")
        # ret = api.get_and_parse_block_info("block_gn.dat")
        # ret = api.get_and_parse_block_info("block.dat")
        ret = api.get_block_dat_ver_up("incon.dat")
        #ret = api.get_and_parse_block_info("mgblock.dat")
        # ret = get_block_info_meta("block.dat")
        #print(api.to_df(ret))
        print((ret))

        # ad3=df3[df3.blockname=='中证500'].code_list



