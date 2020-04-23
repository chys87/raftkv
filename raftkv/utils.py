from google.protobuf import text_format

from .global_pb2 import Conf


def load_conf(conf_file):
    with open(conf_file) as f:
        content = f.read()
    conf = Conf()
    text_format.Parse(content, conf)

    # Set default values
    if conf.heartbeat_interval <= 0:
        conf.heartbeat_interval = 1.0
    if conf.election_timeout_min <= 0:
        conf.election_timeout_min = 6.0
    if conf.election_timeout_max <= 0:
        conf.election_timeout_max = 8.0
    for server in conf.servers:
        if not server.ip:
            server.ip = '127.0.0.1'

    return conf
