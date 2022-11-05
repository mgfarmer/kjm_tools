#!/usr/bin/env python3
"""
My python script template
"""
import sys
import argparse

__author__ = "Kevin Mills"
__version__ = "0.1.0"
__license__ = "MIT"


def cmdline_args():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument("required_int", type=int,
                        help="req number")

    # Required positional argument
    parser.add_argument("arg", help="Required positional argument")

    # Optional argument flag which defaults to False
    parser.add_argument("-f", "--flag", action="store_true", default=False)

    # Optional argument which requires a parameter (eg. -d test)
    parser.add_argument("-n", "--name", action="store", dest="name")

    # Optional verbosity counter (eg. -v, -vv, -vvv, etc.)
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Verbosity (-v, -vv, etc)")

    # Specify output of "--version"
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s (version {version})".format(version=__version__))

    group1 = parser.add_mutually_exclusive_group(required=True)
    group1.add_argument('--enable', action="store_true")
    group1.add_argument('--disable', action="store_false")

    return(parser.parse_args())


def main(args):
    """ Main entry point of the app """
    print("hello world")


if __name__ == '__main__':
    if sys.version_info < (3, 5, 0):
        sys.stderr.write("You need python 3.5 or later to run this script\n")
        sys.stderr.write("You are using: " + sys.version)
        sys.exit(1)

    try:
        args = cmdline_args()
        print(args)
        main(args)
    except:
        sys.exit(1)
