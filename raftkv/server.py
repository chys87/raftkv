from collections import defaultdict
from dataclasses import dataclass, field
import logging
import select
import socket
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .common import MessageClass, Role, message_type_to_class
from . import global_pb2
from .global_pb2 import Conf, Entry, Message, ServerConf


_msg_dispatch: Dict[Tuple[Role, int], Callable[['Server', Message], Any]] = {}


def _dispatch(role: Role, msg_type: int):
    def decorator(func):
        _msg_dispatch[role, msg_type] = func
        return func

    return decorator


@dataclass
class CommonContext:
    servers: List[ServerConf]
    index: int
    heartbeat_interval: float
    election_timeout: float
    current_term: int = 0
    voted_for: Optional[int] = None

    kv: Dict[str, str] = field(default_factory=dict)
    log: List[Entry] = field(default_factory=lambda: [Entry()])
    commit_index: int = 0
    last_applied: int = 0

    @property
    def self(self):
        return self.servers[self.index]

    @property
    def total(self):
        return len(self.servers)

    @property
    def quorum(self):
        return self.total // 2 + 1


@dataclass
class RoleContext:
    pass


@dataclass
class LeaderContext(RoleContext):
    last_heartbeat_sent: float
    next_index: Dict[int, int] = field(
        default_factory=lambda: defaultdict(int))
    match_index: Dict[int, int] = field(
        default_factory=lambda: defaultdict(int))


@dataclass
class CandidateContext(RoleContext):
    request_vote_time: float
    last_vote_received: float = 0
    received_votes: Set[int] = field(default_factory=set)

    def next_timeuot(self):
        return self.request_vote_time + self.cc.election_timeout


@dataclass
class FollowerContext(RoleContext):
    last_heartbeat_received: float
    leader_index: Optional[int] = None


class Server:
    def __init__(self, conf: Conf, index: int):
        # Randomized election timeout
        election_timeout = conf.election_timeout_min + \
            (conf.election_timeout_max - conf.election_timeout_min) \
            * index / len(conf.servers)

        self.cc = CommonContext(
            servers=list(conf.servers),
            index=index,
            heartbeat_interval=conf.heartbeat_interval,
            election_timeout=election_timeout)

    def run(self):
        logging.critical('Server starts running')

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
        self.sock.bind((self.cc.self.ip, self.cc.self.port))

        logging.info(f'Bound to {self.cc.self.ip}:{self.cc.self.port}')

        self.become_follower()

        while True:
            self.receive_and_dispatch()
            self.bookkeeping()

    def receive_and_dispatch(self):
        next_timeout = self.next_timeout()
        now = time.time()
        if next_timeout <= now:
            self.action_timeout()
        else:
            r_ready, _, _ = select.select(
                [self.sock], [], [], next_timeout - now)
            if r_ready:
                msg = self.receive_message()
                if msg is not None:
                    self.action_msg(msg)
            else:
                self.action_timeout()

    def bookkeeping(self):
        if self.cc.last_applied < self.cc.commit_index:
            for i in range(self.cc.last_applied + 1, self.cc.commit_index + 1):
                entry = self.cc.log[i]
                if not entry.value:
                    self.cc.kv.pop(entry.key, None)
                else:
                    self.cc.kv[entry.key] = entry.value
            self.cc.commit_index = self.cc.last_applied
        logging.info(f'last_applied={self.cc.last_applied} '
                     f'commit_index={self.cc.commit_index}')

    def next_timeout(self) -> float:
        if self.role == Role.LEADER:
            return self.leader.last_heartbeat_sent + self.cc.heartbeat_interval
        elif self.role == Role.CANDIDATE:
            return self.candidate.request_vote_time + self.cc.election_timeout
        elif self.role == Role.FOLLOWER:
            return (self.follower.last_heartbeat_received +
                    self.cc.election_timeout)
        else:
            raise ValueError(f'Invalid role: {self.role}')

    def receive_message(self) -> Optional[Message]:
        try:
            msg_bytes, addr = self.sock.recvfrom(65536)
        except socket.error as e:
            logging.error(f'Failed to receive message: {e}')
            return None

        msg = Message()
        try:
            msg.ParseFromString(msg_bytes)
        except ValueError:
            logging.error(f'Failed to parse {len(msg_bytes)} bytes received '
                          f'from {addr}')
            return None

        for i, server in enumerate(self.cc.servers):
            if addr == (server.ip, server.port):
                msg.sender = i
                break
        else:
            msg.sender = -1

        logging.debug(f'Received msg: {msg}')
        return msg

    def action_timeout(self):
        if self.role == Role.LEADER:
            self.action_timeout_leader()
        elif self.role == Role.CANDIDATE:
            self.action_timeout_candidate()
        elif self.role == Role.FOLLOWER:
            self.action_timeout_follower()
        else:
            raise ValueError(f'Invalid role: {self.role}')

    def action_timeout_leader(self):
        '''When leader has a timeout, broadcast a heartbeart
        (an empty AppendEntries request)
        '''
        self.leader.last_heartbeat_sent = time.time()
        msg = Message()
        msg.type = global_pb2.MESSAGE_APPEND_ENTRIES
        msg.term = self.cc.current_term
        self.broadcast(msg)

    def action_timeout_candidate(self):
        '''When candidate has a timeout, initiate a new round of election
        '''
        self.become_candidate()

    def action_timeout_follower(self):
        '''When follower has a timeout, become a candidate'''
        self.become_candidate()

    def action_msg(self, msg: Message):
        msg_cls = message_type_to_class(msg.type)
        if msg_cls in (MessageClass.SERVER_REQUEST,
                       MessageClass.SERVER_RESPONSE) and \
                msg.term > self.cc.current_term:
            logging.info(
                f'Received term {msg.term} > {self.cc.current_term}; '
                f'becoming follower')
            self.cc.current_term = msg.term
            self.cc.voted_for = None
            self.become_follower()
            # Continue to handle the request upon becoming follower

        func = _msg_dispatch.get((self.role, msg.type))
        if func is not None:
            func(self, msg)
        else:
            logging.info(f'Ignored message {self.role}: {msg}')

    @_dispatch(Role.FOLLOWER, global_pb2.MESSAGE_APPEND_ENTRIES)
    def _(self, msg):
        if msg.term < self.cc.current_term:
            logging.info(f'Ignored old message: {self.cc.current_term}')
            return

        self.follower.last_heartbeat_received = time.time()
        self.follower.leader_index = msg.sender

        # TODO: Reply

    # @_dispatch(Role.CANDIDATE, global_pb2.MESSAGE_APPEND_ENTRIES)
    # @_dispatch(Role.LEADER, global_pb2.MESSAGE_APPEND_ENTRIES)
    # def _(self, msg):
    #     raise NotImplementedError

    @_dispatch(Role.FOLLOWER, global_pb2.MESSAGE_REQUEST_VOTE)
    def _(self, msg):
        if msg.term < self.cc.current_term:
            logging.info(f'Ignored old message: {self.cc.current_term}')
            return

        if self.cc.voted_for is not None:
            logging.info(f'Not voting for {msg.sender} '
                         f'(already voted for {self.cc.voted_for})')
            return

        logging.info(f'Voting for {msg.sender}, updated to term {msg.term}')
        self.cc.current_term = msg.term
        self.cc.voted_for = msg.sender
        reply = Message()
        reply.type = global_pb2.MESSAGE_REQUEST_VOTE_RESULT
        reply.term = msg.term
        reply.request_vote_response.vote_granted = True
        self.send(msg.sender, reply)

    @_dispatch(Role.CANDIDATE, global_pb2.MESSAGE_REQUEST_VOTE)
    @_dispatch(Role.LEADER, global_pb2.MESSAGE_REQUEST_VOTE)
    def _(self, msg):
        if msg.term < self.cc.current_term:
            logging.info(f'Ignored old message: {self.cc.current_term}')
        else:
            logging.info(f'Not voting for {msg.sender} (same term {msg.term})')

    @_dispatch(Role.CANDIDATE, global_pb2.MESSAGE_REQUEST_VOTE_RESULT)
    def _(self, msg):
        if msg.term < self.cc.current_term:
            logging.info(f'Ignored old message: {self.cc.current_term}')
            return

        if msg.request_vote_response.vote_granted:
            self.candidate.received_votes.add(msg.sender)
            self.candidate.last_vote_received = time.time()

            if len(self.candidate.received_votes) >= self.cc.quorum:
                self.become_leader()

    def become_follower(self):
        logging.info(f'Become follower, term {self.cc.current_term}')
        self.role = Role.FOLLOWER
        self.follower = FollowerContext(
            last_heartbeat_received=time.time())

    def become_candidate(self):
        self.cc.current_term += 1
        self.cc.voted_for = None
        logging.info(f'Become candidate, term {self.cc.current_term}')
        now = time.time()
        self.role = Role.CANDIDATE
        self.candidate = CandidateContext(request_vote_time=now)
        self.candidate.received_votes.add(self.cc.index)
        msg = Message()
        msg.type = global_pb2.MESSAGE_REQUEST_VOTE
        msg.term = self.cc.current_term
        msg.request_vote.last_log_index = len(self.cc.log) - 1
        msg.request_vote.last_log_term = self.cc.log[-1].term
        self.broadcast(msg)

    def become_leader(self):
        logging.info(f'Become leader, term {self.cc.current_term}')
        now = time.time()
        self.role = Role.LEADER
        self.leader = LeaderContext(last_heartbeat_sent=now)
        self.action_timeout()  # Immediately send heartbeats

    def send(self, recipient_index: int, msg: Message):
        logging.debug(f' ==> [{recipient_index}]: {msg}')
        msg_bytes = msg.SerializeToString()
        recipient = self.cc.servers[recipient_index]
        self.sock.sendto(msg_bytes, (recipient.ip, recipient.port))

    def broadcast(self, msg: Message):
        logging.debug(f' ==> all: {msg}')
        msg_bytes = msg.SerializeToString()
        for i, server in enumerate(self.cc.servers):
            if i != self.cc.index:
                self.sock.sendto(msg_bytes, (server.ip, server.port))
