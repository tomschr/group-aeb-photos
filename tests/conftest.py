import pytest
from unittest.mock import MagicMock, PropertyMock
# from utils import make_exif_entry


def make_exif_entry(filename="IMG_0001.JPG",
                    date="2019:08:26 19:54:10",
                    aebvalue=0,
                    aeb="AEB"):
    return {"SourceFile": filename,
            "EXIF:CreateDate": date,
            "EXIF:DateTimeOriginal": date,
            "EXIF:ModifyDate": date,
            "EXIF:ExposureTime": 0.3,
            "MakerNotes:BracketMode": aeb,
            "MakerNotes:AEBBracketValue": aebvalue,
            # "MakerNotes:BracketValue": ,
            }

# Factory fixture
@pytest.fixture
def exifimage():
    counter = 0
    def _image(aebvalue=0, aeb="AEB", exposuretime=0.3):
        nonlocal counter
        filename = f"IMG_{counter:04}.JPG"
        counter += 1
        date = "2019:08:26 19:54:10"
        return make_exif_entry(filename=filename,
                    date=date,
                    aebvalue=aebvalue,
                    aeb=aeb)
    return _image
