"""Download the official OpenCV Zoo YuNet and SFace ONNX models once."""

import os
from pathlib import Path
from urllib.request import urlopen

MODELS = {
    "face_detection_yunet_2023mar.onnx": "face_detection_yunet",
    "face_recognition_sface_2021dec.onnx": "face_recognition_sface",
}


def main():
    root = Path("models")
    root.mkdir(exist_ok=True)
    for name, folder in MODELS.items():
        target = root / name
        if target.exists():
            print(f"Already present: {target}")
            continue
        url = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/{folder}/{name}"
        temp = target.with_suffix(".download")
        try:
            with urlopen(url, timeout=60) as response, temp.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if temp.stat().st_size < 10000:
                raise ValueError(
                    "Model response too small; refusing incomplete download"
                )
            os.replace(temp, target)
            print(f"Downloaded {target}")
        finally:
            temp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
