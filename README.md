Grouping Exposure Bracketing Images
===================================

Imagine, you visit a beautiful spot and want to shoot some photos.
You think about making it with exposure bracketing (AEB) to merge
the photos later.

However, later you notice you don't know which photos of your big
collection belongs together.

This little script helps to find the right pairings.


Synopsis
--------

```
group-aeb-photos-threads.py [-h] [-v] [--jobs N] [--with-raw] [--json]
                            DIR
```

Arguments:

* `-h`, `--help`
  show this help message and exit
* `-v`
  Raise verbosity level (can be added more than one times)
* `--jobs N`, `-j N`
  Allow N jobs at once; defaults to number of processor cores
* `--with-raw`, `-R`
  Include RAW files
* `--json`
  Output the result as JSON, otherwise as text
* `DIR`
  The directory with images files to group


Dependencies
------------

* `exiftool` from https://exiftool.sourceforge.io/
* Images with EXIF metadata and exposure mode "auto bracketed"


Design
------

The script expects a directory where to search for images. When the user
passes the directory, the script will perform the following steps:

1. Iterate over all files in the directory.
1. Consider files only which contain a specific file extension (.JPG, .CR2 etc)
1. Get the EXIF information of the image file.
1. Extract the information about AEB. If the image does not contain AEB information
    skip the image, otherwise keep it.
1. Extract the date information. As the date can be in different EXIF keys, search
    for it. If cannot be found, use the creating time as a last resort.
1. Sort all image files by their date. It is expected that the date and time
1. Output the result.
