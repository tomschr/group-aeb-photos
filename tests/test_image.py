#
from fractions import Fraction
from unittest.mock import patch, DEFAULT, MagicMock, Mock, PropertyMock

from datetime import datetime

import pytest

# This is a symbolic link to the parent script; it's just here to act
# as a abstract name
import gap


def test_image_is_aeb(exifimage):
    exif = exifimage()    
    filename = exif["SourceFile"]
    with patch("gap.Image") as mockclass:
        inst = mockclass.return_value
        inst.exif.return_value = exif
        img = gap.Image(filename)
        assert img.is_aeb()


def test_image_aebvalue(exifimage):
    exif = exifimage()
    filename = exif["SourceFile"]
    with patch("gap.Image.exif", new_callable=PropertyMock) as mock:
        mock.__get__ = Mock(return_value=exif)
        img = gap.Image(filename)
        assert img.aebvalue == Fraction(0)


def test_image_date(exifimage):
    exif = exifimage()
    filename = exif["SourceFile"]

    with patch("gap.Image.exif", new_callable=PropertyMock) as mock:
        mock.__get__ = Mock(return_value=exif)
        img = gap.Image(filename)
        assert isinstance(img.date, datetime)
        assert img.date.microsecond == 0


def test_image_convert2date():
    date = gap.convert2date("2019:08:26 19:54:10")
    assert date is not None
    assert date.year == 2019 and date.month == 8 and date.day == 26
    assert date.hour == 19 and date.minute == 54 and date.second == 10


def test_image_compare(exifimage):
    exif1 = exifimage()
    exif2 = exifimage(aebvalue="+1/3")

    with patch.object(gap, "getexif_exiftool") as mock:
        mock.side_effect = [exif1, exif2]
        img1 = gap.Image(exif1["SourceFile"])
        img2 = gap.Image(exif2["SourceFile"])
        assert img1 < img2


def test_getexif_exiftool_subprocess_run(monkeypatch):
    filename = "fake-image.jpg"
    def mock_run(*popenargs, **kwargs):
        stdout = b'[{"SourceFile": "%s"}]' % bytes(filename, "UTF-8")
        return gap.subprocess.CompletedProcess(args=popenargs,
                                               returncode=0,
                                               stdout=stdout,
                                               stderr=None,
                                               )

    monkeypatch.setattr(gap.subprocess, "run", mock_run)
    result = gap.getexif_exiftool(filename)
    assert dict(SourceFile=filename) == result


def test_getexif_exiftool_raise(monkeypatch):
    filename = "fake-image.jpg"
    def mock_run(*popenargs, **kwargs):
        stdout = b'[{"SourceFile": "%s"}]' % bytes(filename, "UTF-8")
        return gap.subprocess.CompletedProcess(args=popenargs,
                                               returncode=0,
                                               stdout=stdout,
                                               stderr=None,
                                               )
    def mock_loads(*args, **kwargs):
        raise gap.json.JSONDecodeError("mocked exception", filename, 1)

    monkeypatch.setattr(gap.subprocess, "run", mock_run)
    monkeypatch.setattr(gap.json, "loads", mock_loads)

    with pytest.raises(gap.json.JSONDecodeError):
        result = gap.getexif_exiftool(filename)


def test_image_getexif_exiftool(exifimage):
    exif1 = exifimage()
    exif2 = exifimage(aebvalue="+1/3")

    with patch.object(gap, "getexif_exiftool") as mock:
        mock.side_effect = [exif1, exif2]
        img1 = gap.Image(exif1["SourceFile"])
        img2 = gap.Image(exif2["SourceFile"])
        assert img1.exif != img2.exif
