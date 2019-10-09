"""
Python classes for BMP
"""

from enum import Enum
import ipaddress
import json

class MessageType(Enum):
    ROUTE_MONITORING = 0
    STATISTICS = 1
    PEER_DOWN = 2
    PEER_UP = 3
    INITIATION = 4
    TERMINATION = 5
    ROUTE_MIRRORING = 6

def parse_message(msg_json):
    msg_dict = json.loads(msg_json)
    header = msg_dict['Header']
    msg_type = MessageType(header['Type'])
    if msg_type == MessageType.PEER_DOWN:
        return PeerDownMessage(msg_dict)
    elif msg_type == MessageType.PEER_UP:
        return PeerUpMessage(msg_dict)
    else:
        return Message(msg_type, msg_dict)

class Message:
    def __init__(self, msg_type, msg_dict):
        self._type = msg_type
        src_id = msg_dict['PeerHeader']['PeerBGPID']
        self._src_id = (None if src_id == '' else ipaddress.ip_address(src_id))
        src_as = 0
        if 'PeerAS' in msg_dict['PeerHeader']:
            src_as = msg_dict['PeerHeader']['PeerAS']
        self._src_as = (None if src_as == 0 else src_as)
        self._timestamp = msg_dict['PeerHeader']['Timestamp']

    def __str__(self):
        if (self._src_id == None):
            return '%s' % (self._type.name)
        else:
            return '%s from %s:%d' % (self._type.name, self._src_id, self._src_as)
    def isPeerUp(self):
        return self._type == MessageType.PEER_UP

    def isPeerDown(self):
        return self._type == MessageType.PEER_DOWN

class PeerDownMessage(Message):
    def __init__(self, msg_dict):
        assert MessageType(msg_dict['Header']['Type']) == MessageType.PEER_DOWN
        super().__init__(MessageType.PEER_DOWN, msg_dict)
        if 'LocalAddress' in msg_dict['Body']:
            self._peer = ipaddress.ip_address(msg_dict['Body']['LocalAddress'])
        else:
            self._peer = None

    def edge(self):
        return (self._src_id, self._peer)

class PeerUpMessage(Message):
    def __init__(self, msg_dict):
        assert MessageType(msg_dict['Header']['Type']) == MessageType.PEER_UP
        super().__init__(MessageType.PEER_UP, msg_dict)
        self._peer = ipaddress.ip_address(msg_dict['Body']['LocalAddress'])

    def edge(self):
        return (self._src_id, self._peer)
