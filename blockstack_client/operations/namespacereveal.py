#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
    Blockstack-client
    ~~~~~
    copyright: (c) 2014-2015 by Halfmoon Labs, Inc.
    copyright: (c) 2016 by Blockstack.org

    This file is part of Blockstack-client.

    Blockstack-client is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    Blockstack-client is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.
    You should have received a copy of the GNU General Public License
    along with Blockstack-client. If not, see <http://www.gnu.org/licenses/>.
"""

import pybitcoin
from pybitcoin import embed_data_in_blockchain, serialize_transaction, \
    serialize_sign_and_broadcast, make_op_return_script, \
    make_pay_to_address_script, hex_hash160

from pybitcoin.transactions.outputs import calculate_change_amount

from utilitybelt import is_hex
from binascii import hexlify, unhexlify
import types
import json

from ..b40 import b40_to_hex, bin_to_b40, is_b40
from ..config import *
from ..scripts import *
   
import virtualchain
log = virtualchain.get_logger("blockstack-log")


def serialize_int( int_field, numbytes ):
   """
   Serialize an integer to a hex string that is padlen characters long.
   Raise an exception on overflow.
   """
   
   if int_field >= 2**(numbytes*8) or int_field < -(2**(numbytes*8)):
      raise Exception("Integer overflow (%s bytes)" % (numbytes) )
   
   format_str = "%%0.%sx" % (numbytes*2) 
   hex_str = format_str % int_field 
   
   if len(hex_str) % 2 != 0:
      # sometimes python cuts off the leading zero 
      hex_str = '0' + hex_str
   
   return hex_str
   

def serialize_buckets( bucket_exponents ):
    """
    Serialize the list of bucket exponents.
    There should be 16 buckets, and each one should have an integer between 0 and 15.
    """
    ret = ""
    for i in xrange(0, len(bucket_exponents)):
        ret += "%X" % bucket_exponents[i]
    
    return ret


def serialize_discounts( nonalpha_discount, no_vowel_discount ):
    """
    Serialize the non-alpha and no-vowel discounts.
    They must be between 0 and 15
    """
    return "%X%X" % (nonalpha_discount, no_vowel_discount)


def namespacereveal_sanity_check( namespace_id, version, lifetime, coeff, base, bucket_exponents, nonalpha_discount, no_vowel_discount ):
   """
   Verify the validity of a namespace reveal.
   Return True if valid
   Raise an Exception if not valid.
   """
   # sanity check 
   if not is_b40( namespace_id ) or "+" in namespace_id or namespace_id.count(".") > 0:
      raise Exception("Namespace ID '%s' has non-base-38 characters" % namespace_id)
   
   if len(namespace_id) > LENGTH_MAX_NAMESPACE_ID:
      raise Exception("Invalid namespace ID length for '%s' (expected length between 1 and %s)" % (namespace_id, LENGTH_MAX_NAMESPACE_ID))
   
   if lifetime < 0 or lifetime > (2**32 - 1):
      lifetime = NAMESPACE_LIFE_INFINITE 

   if coeff < 0 or coeff > 255:
      raise Exception("Invalid cost multiplier %s: must be in range [0, 256)" % coeff)
  
   if base < 0 or base > 255:
      raise Exception("Invalid base price %s: must be in range [0, 256)" % base)
  
   if len(bucket_exponents) != 16:
        raise Exception("Exactly 16 buckets required")

   for i in xrange(0, len(bucket_exponents)):
       if bucket_exponents[i] < 0 or bucket_exponents[i] > 15:
          raise Exception("Invalid bucket exponent %s (must be in range [0, 16)" % bucket_exponents[i])
   
   if nonalpha_discount <= 0 or nonalpha_discount > 15:
        raise Exception("Invalid non-alpha discount %s: must be in range [0, 16)" % nonalpha_discount)
    
   if no_vowel_discount <= 0 or no_vowel_discount > 15:
        raise Exception("Invalid no-vowel discount %s: must be in range [0, 16)" % no_vowel_discount)

   return True


# version: 2 bytes
# namespace ID: up to 19 bytes
def build( namespace_id, version, reveal_addr, lifetime, coeff, base, bucket_exponents, nonalpha_discount, no_vowel_discount ):
   """
   Record to mark the beginning of a namespace import in the blockchain.
   This reveals the namespace ID, and encodes the preorder's namespace rules.
   
   The rules for a namespace are as follows:
   * a name can fall into one of 16 buckets, measured by length.  Bucket 16 incorporates all names at least 16 characters long.
   * the pricing structure applies a multiplicative penalty for having numeric characters, or punctuation characters.
   * the price of a name in a bucket is ((coeff) * (base) ^ (bucket exponent)) / ((numeric discount multiplier) * (punctuation discount multiplier))
   
   Example:
   base = 10
   coeff = 2
   nonalpha discount: 10
   no-vowel discount: 10
   buckets 1, 2: 9
   buckets 3, 4, 5, 6: 8
   buckets 7, 8, 9, 10, 11, 12, 13, 14: 7
   buckets 15, 16+:
   
   The price of "john" would be 2 * 10^8, since "john" falls into bucket 4 and has no punctuation or numerics.
   The price of "john1" would be 2 * 10^6, since "john1" falls into bucket 5 but has a number (and thus receives a 10x discount)
   The price of "john_1" would be 2 * 10^6, since "john_1" falls into bucket 6 but has a number and puncuation (and thus receives a 10x discount)
   The price of "j0hn_1" would be 2 * 10^5, since "j0hn_1" falls into bucket 6 but has a number and punctuation and lacks vowels (and thus receives a 100x discount)
   Namespace ID must be base38.
   
   Format:
   
   0     2   3        7     8     9    10   11   12   13   14    15    16    17       18        20                        39
   |-----|---|--------|-----|-----|----|----|----|----|----|-----|-----|-----|--------|----------|-------------------------|
   magic  op  life    coeff. base 1-2  3-4  5-6  7-8  9-10 11-12 13-14 15-16  nonalpha  version   namespace ID
                                                     bucket exponents         no-vowel
                                                                              discounts
   
   """
   
   rc = namespacereveal_sanity_check( namespace_id, version, lifetime, coeff, base, bucket_exponents, nonalpha_discount, no_vowel_discount )
   if not rc:
       raise Exception("Invalid namespace parameters")
    
   # good to go!
   life_hex = serialize_int( lifetime, 4 )
   coeff_hex = serialize_int( coeff, 1 )
   base_hex = serialize_int( base, 1 )
   bucket_hex = serialize_buckets( bucket_exponents )
   discount_hex = serialize_discounts( nonalpha_discount, no_vowel_discount )
   version_hex = serialize_int( version, 2 )
   namespace_id_hex = hexlify( namespace_id )
   
   readable_script = "NAMESPACE_REVEAL 0x%s 0x%s 0x%s 0x%s 0x%s 0x%s 0x%s" % (life_hex, coeff_hex, base_hex, bucket_hex, discount_hex, version_hex, namespace_id_hex)
   hex_script = blockstack_script_to_hex(readable_script)
   packaged_script = add_magic_bytes(hex_script)
   
   return packaged_script


def make_outputs( data, inputs, reveal_addr, change_addr, tx_fee):
    """
    Make outputs for a register:
    [0] OP_RETURN with the name 
    [1] pay-to-address with the *reveal_addr*, not the sender's address.
    [2] change address with the NAMESPACE_PREORDER sender's address
    Raise ValueError if there are not enough inputs to make the transaction
    """
    
    total_to_send = DEFAULT_OP_RETURN_FEE + DEFAULT_DUST_FEE
    
    return [
        # main output
        {"script_hex": make_op_return_script(str(data), format='hex'),
         "value": 0},
    
        # register address
        {"script_hex": virtualchain.make_payment_script(reveal_addr),
         "value": DEFAULT_DUST_FEE},
        
        # change address
        {"script_hex": virtualchain.make_payment_script(change_addr),
         "value": calculate_change_amount(inputs, total_to_send, DEFAULT_DUST_FEE * (len(inputs) + 3)) + tx_fee},
    ]
    
    

def make_transaction( namespace_id, reveal_addr, lifetime, coeff, base_cost, bucket_exponents, nonalpha_discount, no_vowel_discount, payment_addr, blockchain_client, tx_fee=0 ):
   """
   Propagate a namespace.
   
   Arguments:
   namespace_id         human-readable (i.e. base-40) name of the namespace
   reveal_addr          address to own this namespace until it is ready
   lifetime:            the number of blocks for which names will be valid (pass a negative value for "infinite")
   coeff:               cost multipler
   base_cost:           the base cost (i.e. cost of a 1-character name), in satoshis 
   bucket_exponents:    bucket cost exponents to which to raise the base cost 
   nonalpha_discount:   discount multipler for non-alpha-character names 
   no_vowel_discount:   discount multipler for no-vowel names
   """

   namespace_id = str(namespace_id)
   reveal_addr = str(reveal_addr)
   lifetime = int(lifetime)
   coeff = int(coeff)
   base_cost = int(base_cost)
   nonalpha_discount = int(nonalpha_discount)
   no_vowel_discount = int(no_vowel_discount)
   payment_addr = str(payment_addr)
   tx_fee = int(tx_fee)

   assert pybitcoin.b58check_version_byte( payment_addr ) == virtualchain.version_byte, "Only p2pkh reveal addresses are supported"

   bexp = []
   for be in bucket_exponents:
       bexp.append(int(be))

   bucket_exponents = bexp

   assert is_namespace_valid(namespace_id)

   nulldata = build( namespace_id, BLOCKSTACK_VERSION, reveal_addr, lifetime, coeff, base_cost, bucket_exponents, nonalpha_discount, no_vowel_discount )
   
   # get inputs and from public key
   inputs = tx_get_unspents( payment_addr, blockchain_client )
    
   # build custom outputs here
   outputs = make_outputs(nulldata, inputs, reveal_addr, payment_addr, tx_fee)
   
   return (inputs, outputs)


def get_fees( inputs, outputs ):
    """
    Blockstack currently does not allow 
    the subsidization of namespaces.
    """
    return (None, None)


def snv_consensus_extras( name_rec, block_id, blockchain_name_data ):
    """
    Calculate any derived missing data that goes into the check() operation,
    given the block number, the name record at the block number, and the db.
    """
    
    return {}
