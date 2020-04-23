from dataclasses import dataclass
import enum
from typing import List

from .global_pb2 import Conf, ServerConf


class Role(enum.IntEnum):
    FOLLOWER = 1
    CANDIDATE = 2
    LEADER = 3


class MessageClass(enum.IntEnum):
    SERVER_REQUEST = 1
    SERVER_RESPONSE = 2
    CLIENT_REQUEST = 3
    CLIENT_RESPONSE = 4


def message_type_to_class(msg_type: int) -> MessageClass:
    if msg_type < 100:
        return MessageClass.SERVER_REQUEST
    elif msg_type < 200:
        return MessageClass.SERVER_RESPONSE
    elif msg_type < 300:
        return MessageClass.CLIENT_REQUEST
    else:
        return MessageClass.CLIENT_RESPONSE
