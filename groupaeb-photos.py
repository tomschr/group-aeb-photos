#!/usr/bin/python3

"""
"""


__author__ = "Thomas Schraitle <tom_schr@web.de>"
__version__ = "0.1.1"

import argparse
import logging
from logging.config import dictConfig
import multiprocessing as mp
import sys

import PIL.Image

PROC="aeb"

# ----------------------------------------------------------------------------
#: The dictionary, used by :class:`logging.config.dictConfig`
#: use it to setup your logging formatters, handlers, and loggers
#: For details, see https://docs.python.org/3.4/library/logging.config.html#configuration-dictionary-schema
DEFAULT_LOGGING_DICT = {
    'version': 1,
    'disable_existing_loggers': True,
    'formatters': {
        'standard': {'format': '[%(levelname)s] %(message)s'},
    },
    'handlers': {
        'default': {
            'level': 'NOTSET',
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
            },
    },
    'loggers': {
        PROC: {
            'handlers': ['default'],
            'level': 'INFO',
            'propagate': True
            },
    }
}

#: Map verbosity level (int) to log level
LOGLEVELS = {None: logging.ERROR,  # 0
             0: logging.ERROR,
             1: logging.WARNING,
             2: logging.INFO,
             3: logging.DEBUG,
}

# ----------------------------------------------------------------------------
log = logging.getLogger(PROC)


def parsecli(cliargs=None):
    """Parse CLI with :class:`argparse.ArgumentParser` and return parsed result

    :param list cliargs: Arguments to parse or None (=use sys.argv)
    :return: parsed CLI result
    :rtype: :class:`argparse.Namespace`
    """

    # Setup logging and the log level according to the "-v" option
    dictConfig(DEFAULT_LOGGING_DICT)


    parser = argparse.ArgumentParser(description=__doc__,
                                     epilog=(f"Version {__version__} "
                                             f"written by {__author__} ")
                                     )
    # ...
    parser.add_argument("-v",
                        dest="verbose",
                        action='count',
                        help="Raise verbosity level (can be added more than one times)",
                        )
    parser.add_argument("--jobs", "-j",
                        metavar="N",
                        type=int,
                        help="Allow N jobs at once; defaults to number of processor cores",
                        )
    parser.add_argument("dir",
                        metavar="DIR",
                        help="The directory with images files to group",
                        )

    args = parser.parse_args(args=cliargs)


    level = LOGLEVELS.get(args.verbose, logging.DEBUG)
    log.setLevel(level)
    log.debug("CLI args: %s", args)
    return args


def main(cliargs=None):
    """Entry point for the application script

    :param list cliargs: Arguments to parse or None (=use :class:`sys.argv`)
    :return: error code; 0 => everything was succesfull, !0 => error
    :rtype: int
    """
    try:
        args = parsecli(cliargs)
        return 0
    except ValueError as error:
        print(error, file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
