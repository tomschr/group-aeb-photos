#!/usr/bin/python3

"""Group Auto Exposure Bracketing (AEB) photos

Background
   Imagine, you visit a beautiful spot and want to shoot some photos. You
   think about making a exposure bracketing (AEB) to merge the photos later.
   However, later you notice you don't know which photos of your big collection
   belongs together.
   This little script helps to find the right pairings.

Design
   The script expects a directory where to search for images. When the user
   passes the directory, the script will perform the following steps:

   1. Iterate over all files in the directory.
   2. Consider files only which contain a specific file extension (.JPG, .CR2 etc)
   3. Get the EXIF information of the image file.
   4. Extract the information about AEB. If the image does not contain AEB information
      skip the image, otherwise keep it.
   5. Extract the date information. As the date can be in different EXIF keys, search
      for it. If cannot be found, use the creating time as a last resort.
   6. Sort all image files by their date. It is expected that the date and time
   7. Output the result.
"""


__author__ = "Thomas Schraitle <tom_schr@web.de>"
__version__ = "0.5.0"

import argparse
# import asyncio
# from concurrent.futures import ProcessPoolExecutor
from contextlib import suppress
import datetime
from fractions import Fraction
from itertools import groupby
import json
import logging
from logging.config import dictConfig
import math
import os.path
import operator
from pathlib import Path
import subprocess
import sys
import time
import typing

if sys.version_info < (3, 5):
    print("ERROR: Script needs Python version 3.5 or greater",
          file=sys.stderr)
    sys.exit(100)


PROC="aeb"

# ----------------------------------------------------------------------------
#: The dictionary, used by :class:`logging.config.dictConfig`
#: use it to setup your logging formatters, handlers, and loggers
#: For details, see https://docs.python.org/3.4/library/logging.config.html#configuration-dictionary-schema
DEFAULT_LOGGING_DICT = {
    'version': 1,
    'disable_existing_loggers': True,
    'formatters': {
        'standard': {'format': '[%(levelname)-5s] %(message)s'},
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
#CAMERA = {'Canon':
#          ['BracketMode', 'BracketValue', 'AEBBracketValue', 'MeasuredEV2'],
#          'Nikon':
#              ['???'],
#          'Sony':
#              ['???'],
#          'Fuji':
#              ['???'],
#          'Panasonic':
#              ['???'],
#    }


IMAGE_TYPES = (".JPG", ".JPEG", ".jpg", ".jpeg",
               ".PNG", ".png",
               ".TIF", ".TIFF", ".tif", ".tiff")
IMAGE_RAW_TYPES = (".ARW", ".CR2", ".DCR", ".DNG", ".K25", ".KDC", ".MRW",
                   ".NEF", ".ORF", ".RAW", ".RW2", ".PEF", ".RAF", ".SR2",
                   ".SRF", ".X3F", )


DATA_KEYS: tuple = ("EXIF:CreateDate", "EXIF:DateTimeOriginal", "EXIF:ModifyDate",
                    # This is a "fake" entry which doesn't exist in EXIF, but it
                    # is used as a last resort to get at least one date/time
                    # if the above keys cannot be found
                    # "File:CreationTime"
                    )


# ----------------------------------------------------------------------------

log = logging.getLogger(PROC)


# ----------------------------------------------------------------------------
def getexif_exiftool(filename: os.PathLike) -> dict:
    """Get EXIF information from a filename (it will be retrieved by the
       exiftool)

    :param filename: the image filename
    :return: Dictionary
    """
    cmd = f"exiftool -json -G {filename}"
    try:
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE)
        log.debug("Got EXIF data: %i bytes", len(result.stdout))
        return json.loads(result.stdout)[0]
    # except subprocess.CalledProcessError as err:
    #     log.fatal(err)
    except json.JSONDecodeError as err:
        log.fatal("Problem converting exiftool -> JSON: %s", err)
        raise


def get_all_image_files(directory: str, with_raw=False):
    """Yield all image types of a given directory; include RAW files if
    with_raw is set to True

    :param directory: The directory to search for
    :type directory: str
    :param bool with_raw: Include raw file types into result?
    :yield: yield a image filename
    """
    log.debug("Investigating directory %r, using RAW files=%s", directory, with_raw)
    for img in Path(directory).iterdir():
        if (img.is_file() and img.suffix in IMAGE_TYPES) or (with_raw and img.suffix in IMAGE_RAW_TYPES):
            yield Image(img)


def is_timerange(this: datetime.datetime, other: datetime.datetime, seconds: int):
    """Compare if a time other is in the range
        of [this-seconds...this+seconds]

    :param this: The datetime object
    :param other: the datetime object to compare with
    :param seconds: the seconds that spans the range between this-seconds and this+seconds
    :return: True if other is in the range, False otherwise

    Example:
    >>> import datetime
    >>> d1 = datetime.datetime(2019, 8, 26, 19, 54, 0)
    >>> d2 = datetime.datetime(2019, 8, 26, 19, 54, 4)
    >>> is_timerange(d1, d2, 5)
    True
    >>> is_timerange(d1, d2, 2)
    False
    """
    delta = datetime.timedelta(seconds=seconds)
    return abs(other - this) <= delta


def aebrange(count: int):
    """Returns a list with offsets of exposure bracketing.
    Currently, it makes only sense to have 3, 5, or 7 exposure bracketing
    images

    :param int count: number of images to detect (3, 5, or 7)
    :return: range with 3, 5 or 7 numbers

    >>> aebrange(3)
    range(-1, 2)
    >>> list(aebrange(3))
    [-1, 0, 1]
    >>> aebrange(5)
    range(-2, 3)
    >>> aebrange(7)
    range(-3, 4)
    >>> aebrange(4)
    Traceback (most recent call last):
    ...
    AssertionError: Expected odd number
    >>> aebrange(2)
    Traceback (most recent call last):
    ...
    AssertionError: Expect number between >=3 and <=7
    """
    assert 3 <= count <= 7, "Expect number between >=3 and <=7"
    assert count % 2, "Expected odd number"
    start = -(count // 2)
    end = (count // 2) + 1
    return range(start, end)


class Image:
    """Class of an image file
    """
    DATA_KEYS: tuple = ("EXIF:CreateDate", "EXIF:DateTimeOriginal", "EXIF:ModifyDate",
                        # This is a "fake" entry which doesn't exist in EXIF, but it
                        # is used as a last resort to get at least one date/time
                        # if the above keys cannot be found
                        # "File:CreationTime"
                        )
    def __init__(self, file: os.PathLike):
        self.file : os.PathLike = file
        self._exif = None
        self._date = None
        self._aeb = None
        self._aebvalue = None

    @property
    def exif(self):
        """Exif data of the current image file
        """
        if self._exif is not None:
            return self._exif
        self._exif = getexif_exiftool(self.file)
        return self._exif

    @property
    def date(self):
        """Date of the current image file
        """
        if self._date is not None:
            return self._date
        self._date = self._get_date()
        return self._date

    @property
    def aebvalue(self):
        """Returns the MakerNotes:AEBBracketValue"""
        if self._aebvalue is None:
            self._aebvalue = Fraction(self.exif["MakerNotes:AEBBracketValue"])
        return self._aebvalue

    def _get_date(self):
        """Extract the date from the EXIF data. Try to make several attempts and
        search for "EXIF:CreateDate", "EXIF:DateTimeOriginal", "EXIF:ModifyDate"
        (in that order).
        If none of these keys where found, use the creation time of the file as
        a last resort.

        :return: a date
        :rtype: :class:`datetime.datetime`
        """
        for key in Image.DATA_KEYS:
            date = self.convert2date(self.exif.get(key))
            if date is not None:
                return date

        # Ok, when we reached this point, we haven't found the EXIF date time
        # data. As a last resort, we fallback to file time:
        t = os.path.getmtime(self.file)
        return datetime.datetime.fromtimestamp(t)

    def convert2date(self, string):
        """Convert a string of the format "YEAR:MONTH:DAY HOUR:MINUTE:SECOND"
        into a datetime.datetime object

        :param str|None string: the string containing the date and time (or None)
        :return: The converted datetime object or None
        :rtype: :class:`datetime.datetime` | None
        """
        try:
            d = datetime.datetime.strptime(string, "%Y:%m:%d %H:%M:%S")
            # We don't care about microseconds, so just in case we set it to zero to make
            # comparisons easier:
            return d.replace(microsecond=0)
        except (TypeError, ValueError):
            # string doesn't match or was None
            return None

    def is_aeb(self) -> bool:
        """Checks, if the image file belongs to an AEB group"""
        with suppress(KeyError):
            mode = self.exif['MakerNotes:BracketMode']
            # Only add images which are shot in AEB mode:
            if mode == "AEB":
                return True
        return False

    def almostequaltime(self, other):
        """Checks, wheather another image contains the same creation time
        OR is in the time range of exposure time

        d1 = "2019:08:26 19:54:10" ExposureTime= 1/8
        d2 = "2019:08:26 19:54:10" ExposureTime= 0.3
        """
        key_exposure = "EXIF:ExposureTime"
        # key_time = "EXIF:CreateDate"
        thisdate = self.date
        otherdate = other.date

        # The heuristic of checking how close an other image is
        #
        with suppress(KeyError):
            delta = otherdate - thisdate
            seconds = delta.total_seconds()
            # We use math.isclose to avoid any imprecisions
            # If both time stamps are equal (=very close), we can stop here
            # and pretend they are true
            if math.isclose(seconds, 0.0, abs_tol=0.01):
                return True

            # If the time stamp aren't close, we need to consider the
            # exposure time
            # We check, if the exposure time is "close" to 1.0.
            # If it's smaller than 1s, we use 1s, otherwise we use the real value
            exposuretime = Fraction(self.exit[key_exposure])
            if exposuretime < 1:
                seconds = 1
            else:
                # We use only integers, not float here
                seconds = int(float(exposuretime)) 

            # Now we need to check if the otherdate is in the range of
            # thisdate +/- seconds:
            return is_timerange(thisdate, otherdate, seconds)

        return False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.file})"

    def __str__(self) -> str:
        return f"{self.file}: {self.date}"

    def __lt__(self, other):
        """Return self < value"""
        # To compare two images (algorithm details):
        # 1. First compare the creation time, extracted from the EXIF information
        #    a. If it's equal, compare MakerNotes:AEBBracketValue and derive
        #       from that the ordering
        #    b. If it's not equal, 
        thisdate = self.date
        otherdate = other.date

        with suppress(KeyError):
            delta = otherdate - thisdate
            seconds = delta.total_seconds()
            # We use math.isclose to avoid any imprecisions
            # If both time stamps are equal (=very close), we only need
            # to compare the AEBBracketValues
            if math.isclose(seconds, 0.0, abs_tol=0.01):
                return self.aebvalue < other.aebvalue
            else:
                # If the time stamp aren't close, we need to consider the
                # exposure time
                # We check, if the exposure time is "close" to 1.0.
                # If it's smaller than 1s, we use 1s, otherwise we use the real value
                exposuretime = Fraction(self.exit["EXIF:ExposureTime"])
                if exposuretime < 1:
                    seconds = 1
                else:
                    # We use only integers, not float here
                    seconds = int(float(exposuretime)) 

                # Now we need to check if the otherdate is in the range of
                # thisdate +/- seconds:
                if not is_timerange(thisdate, otherdate, seconds):
                    return False
                # If the otherdate is in the range, we need to consider the
                # MakerNotes:AEBBracketValue
                # We compare, if the current value is less than the other: 
                return self.aebvalue < other.aebvalue

        # If we get any KeyError exception, then Python jumps here
        return False

    def __eq__(self, other):
        exif = self.exif
        oexif = other.exif
        with suppress(KeyError):
            # Handle case where each of the image is not an AEB
            if self.is_aeb() != other.is_aeb():
                return False

        return False


# ----------------------------------------------------------------------------
def parsecli(cliargs=None):
    """Parse CLI with :class:`argparse.ArgumentParser` and return parsed result

    :param list cliargs: Arguments to parse or None (=use sys.argv)
    :return: parsed CLI result
    :rtype: :class:`argparse.Namespace`
    """

    # Setup logging and the log level according to the "-v" option
    dictConfig(DEFAULT_LOGGING_DICT)


    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
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
    parser.add_argument("--with-raw", "-R",
                        action="store_true",
                        dest="withraw",
                        default=False,
                        help="Include RAW files")
    parser.add_argument("dir",
                        metavar="DIR",
                        help="The directory with images files to group",
                        )

    args = parser.parse_args(args=cliargs)

    level = LOGLEVELS.get(args.verbose, logging.DEBUG)
    log.setLevel(level)
    log.debug("CLI args: %s", args)
    return args


# ----------------------------------------------------------------------------
def convert2date(string):
    """Convert a string of the format "YEAR:MONTH:DAY HOUR:MINUTE:SECOND"
    into a datetime.datetime object

    :param str|None string: the string containing the date and time (or None)
    :return: The converted datetime object or None
    :rtype: :class:`datetime.datetime` | None
    """
    try:
        d = datetime.datetime.strptime(string, "%Y:%m:%d %H:%M:%S")
        # We don't care about microseconds, so just in case we set it to zero to make
        # comparisons easier:
        return d.replace(microsecond=0)
    except (TypeError, ValueError):
        # string doesn't match or was None
        return None


# ----------------------------------------------------------------------------
def produce(args: argparse.Namespace):
    """

    :param args: the parsed CLI result
    :type args: :class:`argparse.Namespace`
    :return:
    """
    for image in get_all_image_files(args.dir, with_raw=args.withraw):
        log.debug("Investigating image file %s", image)
        # exif = getexif_exiftool(image)
        # date = get_date_from_exif(image, exif)
        if image.is_aeb():
            yield image
        #if check_if_aeb_image(image, exif):
        #    yield image, date, exif


def process(args: argparse.Namespace):
    """Process the image files asynchronosly

    :param args: the parsed CLI result
    :type args: :class:`argparse.Namespace`
    """
    log.debug("process...")
    if not Path(args.dir).exists():
        raise NotADirectoryError("Directory %r does not exist" % args.dir)

    #
    try:
        g_prod = produce(args)
        for date, g in groupby(g_prod, operator.attrgetter('date')):
            print("Group for date", date.isoformat())
            # print("    ", ",".join(list(g)))
            for img in g:
                print("    ", str(img))

    except KeyboardInterrupt:
        # Received Ctrl+C
        log.fatal("Aborted.")
        return 1

    return 0

# ----------------------------------------------------------------------------
def main(cliargs=None):
    """Entry point for the application script

    :param list cliargs: Arguments to parse or None (=use :class:`sys.argv`)
    :return: error code; 0 => everything was succesfull, !=0 => error
    :rtype: int
    """
    try:
        args = parsecli(cliargs)
        start = time.perf_counter()
        result = process(args)
        end =  time.perf_counter()
        log.info("Processing took %.2fs", end - start)
        return result
    except ValueError as error:
        log.error(error)
    except  NotADirectoryError as error:
        log.fatal(error)
    except Exception as error:
        log.fatal(error, exc_info=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
