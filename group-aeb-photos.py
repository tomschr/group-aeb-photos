#!/usr/bin/python3

"""Group Auto Exposure Bracketing (AEB) photos
"""


__author__ = "Thomas Schraitle <tom_schr@web.de>"
__version__ = "0.1.1"

import argparse
import asyncio
from concurrent.futures import ProcessPoolExecutor
import json
import logging
from logging.config import dictConfig
from pathlib import Path
import subprocess
import sys


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


# ----------------------------------------------------------------------------

log = logging.getLogger(PROC)


# ----------------------------------------------------------------------------
def getexif_exiftool(filename: Path):
    """Get EXIF information from a filename

    :param filename: the image filename
    :type filename: :class:`pathlib.Path`
    :return: Dictionary
    :rtype: dict
    """
    cmd = f"exiftool -json -G {filename}"
    try:
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE)
        log.debug("Got EXIF data: %i bytes", len(result.stdout))
        return json.loads(result.stdout)[0]
    except subprocess.CalledProcessError as err:
        log.fatal(err)
    except json.JSONDecodeError as err:
        log.fatal("Problem converting exiftool -> JSON: %s", err)
        raise

    #return {"SourceFile": filename.name,
    #         "ExifTool": {
    #             "ExifToolVersion": 10.80,
    #             },
    #        "File": {
    #            "FileName": filename.name,
    #            },
    #        "EXIF": {},
    #        "MakerNotes": {},
    #        "XMP": {},
    #        "IPTC": {},
    #        "Composite": {},
    #        }


def get_all_image_files(directory: str, with_raw=False):
    """Yield all image types of a given directory; include RAW files if
    with_raw is set to True

    :param directory: The directory to search for
    :type directory: str
    :param bool with_raw: Include raw file types into result?
    :yield: yield a image filename
    """
    log.debug("Investigating directory %r, using RAW files=%s", directory, with_raw)
    for q in Path(directory).iterdir():
        if (q.is_file() and q.suffix in IMAGE_TYPES) or (with_raw and q.suffix in IMAGE_RAW_TYPES):
            yield q


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
async def aio_produce(queue: asyncio.Queue, args: argparse.Namespace):
    """Produce images and put it in queue

    :param queue: the shared queue
    :type queue: :class:`asyncio.Queue`
    """
    for image in get_all_image_files(args.dir, with_raw=args.withraw):
        log.debug("Adding %s to queue", str(image))
        await queue.put(image)

    # poison pill to signal all the work is done
    await queue.put(None)


async def aio_consume(queue: asyncio.Queue, result: asyncio.Queue, loop):
    """Consume from queue and put in result queue

    :param queue: the shared queue
    :type queue: :class:`asyncio.Queue`
    :param result: the result queue
    :type result: :class:`asyncio.Queue`
    """
    while True:
        # coroutine will be blocked if queue is empty
        image = await queue.get()

        # if poison pill is detected, exit the loop
        if image is None:
            break

        with ProcessPoolExecutor() as pool:
            exif = await loop.run_in_executor(pool, getexif_exiftool, image)
            log.info("%s:", image.name)
            # log.debug(exif)
            log.debug("  CreateDate=%s", exif.get('EXIF:CreateDate'))

            # TODO: Maybe filter the images to those that are contains AEB
            try:
                vendor = exif["EXIF:Make"]  # exif['EXIF']['Make']
                log.debug("  Vendor=%s", vendor)

            except KeyError:
                log.warning("Skipped image %s as it doesn't contain "
                            "EXIF.Make",
                            image)

            try:
                mode = exif['MakerNotes:BracketMode']  # exif['MakerNotes']['BracketMode']

                # Only add images which are shot in AEB mode:
                if mode == "AEB":
                    log.info("  AEB image=%s", bool(mode == "AEB"))
                    result.put({image: exif})
            except KeyError:
                log.warning(" not a AEB image. Skipping.")

        # signal that the current task from the queue is done
        # and decrease the queue counter by one
        queue.task_done()

        # poison pill to signal all the work is done
        await result.put(None)


async def aio_collect(queue: asyncio.Queue, loop):
    """Collect the AEB images

    :param queue: the shared queue
    :type queue: :class:`asyncio.Queue`
    :param loop: the asyncio event loop
    :type queue: :class:`asyncio.selector_events.BaseSelectorEventLoop`
    """
    while True:
        # coroutine will be blocked if queue is empty
        image = await queue.get()

        # if poison pill is detected, exit the loop
        if image is None:
            break

        log.debug("Processing %s", image)
        queue.task_done()
    return "Done."


def aio_process(args: argparse.Namespace):
    """Process the image files asynchronosly

    :param args: the parsed CLI result
    :type args: :class:`argparse.Namespace`
    """
    if not Path(args.dir).exists():
        raise NotADirectoryError("Directory %r does not exist" % args.dir)
    loop = asyncio.get_event_loop()
    log.debug("asyncio event loop: %s", type(loop))
    #
    queue = asyncio.Queue(loop=loop)
    result = asyncio.Queue(loop=loop)

    producer_coro = aio_produce(queue, args)
    consumer_coro = aio_consume(queue, result, loop)
    collect_coro = aio_collect(result, loop)

    tasks = (producer_coro, consumer_coro, collect_coro)
    try:
        responses = loop.run_until_complete(asyncio.gather(*tasks))
        # for resp in responses:
        #     print(resp)
    except KeyboardInterrupt:
        # Received Ctrl+C
        asyncio.gather(*asyncio.Task.all_tasks()).cancel()

    finally:
        loop.stop()
        loop.close()
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
        result = aio_process(args)
        return result
    except ValueError as error:
        log.error(error)
    except  NotADirectoryError as error:
        log.fatal(error)
    except Exception as error:
        log.fatal(error)
    return 1


if __name__ == "__main__":
    sys.exit(main())
