import argparse

from . import utils


def main():
    parser = argparse.ArgumentParser(description='raftkv client')
    parser.add_argument('-c', '--conf_file', help='Config file',
                        default='raftkv.pbtxt')
    args = parser.parse_args()
    print(args)

    conf = utils.load_conf(args.conf_file)
    print(conf)


if __name__ == '__main__':
    main()
