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
__version__ = "0.6.0"

import argparse
import datetime
import json
import logging
import os.path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from concurrent.futures import as_completed
from contextlib import suppress
from logging.config import dictConfig
from pathlib import Path
from typing import Generator, Optional, Union

PROC = "aeb"

# ----------------------------------------------------------------------------
# Types
# PathType = TypeVar('PathType', str, os.PathLike, Path)
PathType = Union[str, Path, os.PathLike]

# ----------------------------------------------------------------------------
#: The dictionary, used by :class:`logging.config.dictConfig`
#: use it to setup your logging formatters, handlers, and loggers
#: For details,
#: see https://docs.python.org/3/library/logging.config.html#configuration-dictionary-schema
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
             # 0: logging.ERROR,
             0: logging.WARNING,
             1: logging.INFO,
             2: logging.DEBUG,
             }

# ----------------------------------------------------------------------------
# Logging
log = logging.getLogger(PROC)


class NotAnImageFileError(OSError):
    """Exception which is raised if the image file type does not contain the correct
       extension (be it a "normal" image file and a "raw" type
    """


class Image:
    """Class of an image file"""
    DATA_KEYS: tuple = ("EXIF:CreateDate", "EXIF:DateTimeOriginal", "EXIF:ModifyDate",
                        # This is a "fake" entry which doesn't exist in EXIF, but it
                        # is used as a last resort to get at least one date/time
                        # if the above keys cannot be found
                        # "File:CreationTime"
                        )
    #: Normal file types
    IMAGE_TYPES = (".JPG", ".JPEG", ".jpg", ".jpeg",
                   ".PNG", ".png",
                   ".TIF", ".TIFF", ".tif", ".tiff")
    #: Raw file types
    IMAGE_RAW_TYPES = (".ARW", ".CR2", ".DCR", ".DNG", ".K25", ".KDC", ".MRW",
                       ".NEF", ".ORF", ".RAW", ".RW2", ".PEF", ".RAF", ".SR2",
                       ".SRF", ".X3F",)

    def __init__(self, filename: PathType):
        """Initialize the Image class with a path like object of the image filename

        :param filename: the image file name
        """
        # log.debug("Initializer for %s", filename)
        self.image = filename
        self._exif = None
        self._date = None
        self._aeb = None

    @property
    def image(self) -> Path:
        """The image filename"""
        return self._image

    @image.setter
    def image(self, filename: PathType):
        filename = Path(filename)
        if Image._is_normal_type(filename) or Image._is_raw_type(filename):
            self._image = filename
        else:
            raise NotAnImageFileError(filename)

    @property
    def exif(self) -> dict:
        """Exif data of the current image file
        """
        if self._exif is not None:
            return self._exif
        self._exif = getexif_exiftool(self.image)
        return self._exif

    @property
    def date(self) -> datetime.datetime:
        """Date of the current image file
        """
        self.date = self._date
        return self._date

    @date.setter
    def date(self, date: Optional[datetime.datetime]):
        if date is not None:
            self._date = date
        self._date = self._get_date()

    def _get_date(self) -> datetime.datetime:
        """Extract the date from the EXIF data. Try to make several attempts and
        search for "EXIF:CreateDate", "EXIF:DateTimeOriginal", "EXIF:ModifyDate"
        (in that order).
        If none of these keys where found in the EXIF data, use the creation time
        of the file as a last resort.

        :return: a valid datetime object
        """
        for key in Image.DATA_KEYS:
            date = self.convert2date(self.exif.get(key))
            if date is not None:
                return date

        # Ok, when we reached this point, we haven't found the EXIF date time
        # data. As a last resort, we fallback to file time:
        t = os.path.getmtime(self.image)
        return datetime.datetime.fromtimestamp(t)

    def convert2date(self, string: str) -> Optional[datetime.datetime]:
        """Convert a string of the format "YEAR:MONTH:DAY HOUR:MINUTE:SECOND"
        into a datetime.datetime object

        :param str|None string: the string containing the date and time (or None)
        :return: The converted datetime object or None
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
            # TODO: Currently, this works for Canon cameras.
            #  Make it possible to support other camera vendors
            mode = self.exif['MakerNotes:BracketMode']
            # Only add images which are shot in AEB mode:
            if mode == "AEB":
                return True
        return False

    @staticmethod
    def _is_raw_type(filename: PathType) -> bool:
        """Internal function to check a filename if this a RAW image file

        :param filename: the filename to check for RAW
        :return: the boolean value
        """
        return Path(filename).suffix in Image.IMAGE_RAW_TYPES

    @staticmethod
    def _is_normal_type(filename: PathType) -> bool:
        """Internal function to check if this is a 'normal' image file

        :param filename:
        :return: the boolean value
        """
        return Path(filename).suffix in Image.IMAGE_TYPES

    def is_raw(self) -> bool:
        """Checks, if the image type is a raw file"""
        return self._is_raw_type(self.image)
        #    self.image.suffix in Image.IMAGE_RAW_TYPES

    def is_normal(self) -> bool:
        """Checks, if the image type is a normal type (not raw)"""
        return self._is_normal_type(self.image)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.image!r})"

    def __str__(self) -> str:
        return f"{self.image}: {self.date}"


# ----------------------------------------------------------------------------
def getexif_exiftool(filename: PathType) -> dict:
    """Get EXIF information from a filename (it will be retrieved by the
       exiftool)

    :param filename: the image filename
    :return: Dictionary with EXIF metadata
    """
    cmd = f"exiftool -json -G {filename}"
    try:
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE)
        log.debug("Got EXIF data from %s: %i bytes", filename, len(result.stdout))
        return json.loads(result.stdout)[0]
    # except subprocess.CalledProcessError as err:
    #     log.fatal(err)
    except json.JSONDecodeError as err:
        log.fatal("Problem converting exiftool -> JSON: %s", err)
        raise


def get_all_image_files(directory: PathType, with_raw: bool = False) -> Generator[Image, None, None]:
    """Yield all image types of a given directory; include RAW files if
    with_raw is set to True

    :param directory: The directory to search for
    :param with_raw: Include raw file types into result?
    :yield: yield a image filename
    """
    log.debug("Investigating directory %r, using RAW files=%s", directory, with_raw)
    for img in Path(directory).iterdir():
        try:
            img = Image(img)
            if img.is_normal() or (img.is_raw() and with_raw):
                yield img
        except NotAnImageFileError:
            continue


# ----------------------------------------------------------------------------
def parsecli(cliargs: Optional[list] = None) -> argparse.Namespace:
    """Parse CLI with :class:`argparse.ArgumentParser` and return parsed result

    :param cliargs: Arguments to parse or None (=use sys.argv)
    :return: parsed CLI result
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
                        default=4,
                        help="Allow N jobs at once; defaults to number of processor cores",
                        )
    parser.add_argument("--with-raw", "-R",
                        action="store_true",
                        dest="withraw",
                        default=False,
                        help="Include RAW files")
    parser.add_argument("--json",
                        action="store_true",
                        default=False,
                        help="Output the result as JSON, otherwise as text"
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


# ----------------------------------------------------------------------------
def consume(image: Image) -> Optional[Image]:
    """Consume an image file

    :return: an Image object
    """
    if image.is_aeb():
        return image


def process(args: argparse.Namespace) -> dict:
    """Process the image files in threads

    :param args: the parsed CLI result
    :return: the AEB images grouped by time
       { 'ISODATE1': [Image('IMG1'), Image('IMG2), Image('IMG3')],
         'ISODATE2': [Image('IMG4')],
         # ...
       }
    """
    log.debug("process...")

    result = {}
    with PoolExecutor(max_workers=args.jobs) as executor:
        todos = []
        for image in get_all_image_files(args.dir, with_raw=args.withraw):
            log.debug("Add image %s to future", image)
            future = executor.submit(consume, image)
            todos.append(future)

        for future in as_completed(todos):
            image = future.result()
            if image is None:
                continue
            # We use the ISO format for datetime object to make it able to serialize it
            result.setdefault(image.date.isoformat(), []).append(image)

    return result


def output_result(groups: dict, args: argparse.Namespace):
    """Output result dictionary either on stdout or as JSON
    """
    if args.json:
        def default(obj):
            if isinstance(obj, Image):
                return str(obj.image)

        print(json.dumps(groups, indent=4, default=default))
    else:
        for date in sorted(groups.keys()):
            print(date)
            for img in groups[date]:
                print("   ", img.image)


# ----------------------------------------------------------------------------
def main(cliargs: Optional[list] = None) -> int:
    """Entry point for the application script

    :param cliargs: Arguments to parse or None (=use :class:`sys.argv`)
    :return: error code; 0 => everything was succesfull, !=0 => error
    """
    try:
        args = parsecli(cliargs)
        if not Path(args.dir).exists():
            raise NotADirectoryError("Directory %r does not exist" % args.dir)

        start = time.perf_counter()
        result = process(args)
        output_result(result, args)
        end = time.perf_counter()
        log.info("Processing took %.2fs", end - start)
        return 0
    except ValueError as error:
        log.error(error)
    except NotADirectoryError as error:
        log.fatal(error)
    except Exception as error:
        log.fatal(error, exc_info=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
