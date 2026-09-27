"""The original robot pan formula, shared without any positivity overrides."""


def pan_for(face, width):
    x, _y, face_width, _height = face
    return 160 - ((x + face_width // 2) / width) * 140
