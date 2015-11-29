#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
    Registrar
    ~~~~~

    copyright: (c) 2014-2015 by Halfmoon Labs, Inc.
    copyright: (c) 2016 by Blockstack.org

This file is part of Registrar.

    Registrar is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    Registrar is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with Registrar. If not, see <http://www.gnu.org/licenses/>.
"""

from .states import nameRegistered, profileonBlockchain, ownerName

from .blockchain import get_block_height, txRejected
from .blockchain import get_tx_confirmations
from .blockchain import preorderRejected

from .db import preorder_queue, register_queue, update_queue, transfer_queue

from .utils import get_hash
from .utils import config_log
from .utils import pretty_print as pprint

from .config import DHT_IGNORE

log = config_log(__name__)


def alreadyinQueue(queue, fqu):

    check_queue = queue.find_one({"fqu": fqu})

    if check_queue is not None:
        return True

    return False


def add_to_queue(queue, fqu, payment_address=None, tx_hash=None,
                 owner_address=None, transfer_address=None,
                 profile=None, profile_hash=None):

    new_entry = {}

    # required for all queues
    new_entry['fqu'] = fqu
    new_entry['payment_address'] = payment_address
    new_entry['tx_hash'] = tx_hash

    new_entry['block_height'] = get_block_height()

    # optional, depending on queue
    new_entry['owner_address'] = owner_address
    new_entry['transfer_address'] = transfer_address
    new_entry['profile'] = profile
    new_entry['profile_hash'] = profile_hash

    queue.save(new_entry)


def cleanup_rejected_tx(queue):

    for entry in queue.find(no_cursor_timeout=True):

        if txRejected(entry['tx_hash'], entry['block_height']):

            log.debug("TX rejected by network, removing TX: \
                      %s" % entry['tx_hash'])
            queue.remove({"fqu": entry['fqu']})


def display_queue(queue):

    for entry in queue.find():

        try:
            confirmations = get_tx_confirmations(entry['tx_hash'])
        except:
            continue

        log.debug('-' * 5)
        log.debug("%s %s" % (queue.name, entry['fqu']))
        log.debug("(%s, confirmations %s)" % (entry['tx_hash'],
                                              confirmations))
        log.debug("payment: %s" % entry['payment_address'])
        log.debug("owner: %s" % entry['owner_address'])

        if entry['payment_address'] == entry['owner_address']:
            log.debug("problem")


def cleanup_register_queue():

    for entry in preorder_queue.find():

        if nameRegistered(entry['fqu']):
            log.debug("Name registered. Removing preorder: %s" % entry['fqu'])
            preorder_queue.remove({"fqu": entry['fqu']})

        # clear stale preorder
        if preorderRejected(entry['tx_hash']):
            log.debug("Removing stale preorder: %s"
                      % entry['fqu'])
            preorder_queue.remove({"fqu": entry['fqu']})

    for entry in register_queue.find():

        if nameRegistered(entry['fqu']):
            log.debug("Name registered. Removing register: %s" % entry['fqu'])
            register_queue.remove({"fqu": entry['fqu']})

        # logic to remove registrations > say 140 confirmations
        # need better name for func than preorderRejected
        if preorderRejected(entry['tx_hash']):
            log.debug("Removing stale register op: %s"
                      % entry['fqu'])
            register_queue.remove({"fqu": entry['fqu']})

    cleanup_rejected_tx(preorder_queue)
    cleanup_rejected_tx(register_queue)


def cleanup_update_queue():

    for entry in update_queue.find():

        fqu = entry['fqu']
        profile = entry['profile']

        if profileonBlockchain(fqu, profile):
            log.debug("Profile hash updated: %s" % fqu)
            update_queue.remove({"fqu": entry['fqu']})


def cleanup_transfer_queue():

    for entry in transfer_queue.find():

        fqu = entry['fqu']
        try:
            transfer_address = entry['transfer_address']
        except:
            log.debug("Transfer address not saved")
            exit(0)

        if ownerName(fqu, transfer_address):
            log.debug("Transferred: %s" % fqu)
            transfer_queue.remove({"fqu": entry['fqu']})


def display_queue_info():

    display_queue(preorder_queue)
    display_queue(register_queue)
    display_queue(update_queue)
    display_queue(transfer_queue)
