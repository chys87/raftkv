import argparse
import logging

from .server import Server
from . import utils


def main():
    parser = argparse.ArgumentParser(description='raftkv server')
    parser.add_argument('-c', '--conf_file',
                        help='Config file (default: raftkv.pbtxt)',
                        default='raftkv.pbtxt')
    parser.add_argument('-i', '--index', type=int, help='Current server index',
                        required=True)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG,
        format='[\033[31;1m%(asctime)s\033[0m] '
               '[\033[32;1m%(levelname)s\033[0m] [\033[33;1m' +
               str(args.index) +
               '\033[0m] %(message)s')

    conf = utils.load_conf(args.conf_file)
    server = Server(conf, args.index)
    server.run()


if __name__ == '__main__':
    main()
