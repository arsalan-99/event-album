from typing import Optional
from pathlib import Path
from .face_embedder import FaceEmbedder, FaceDetection

DEFAULT_WEIGHTS_DIR = Path(__file__).parent / "weights"
DEFAULT_DETECTOR_PATH = DEFAULT_WEIGHTS_DIR / "face_detection_yunet_2023mar.onnx"
DEFAULT_RECOGNIZER_PATH = DEFAULT_WEIGHTS_DIR / "face_recognition_sface_2021dec.onnx"

_face_embedder_instance: Optional[FaceEmbedder] = None


def get_face_embedder(
    detector_path: Path = DEFAULT_DETECTOR_PATH,
    recognizer_path: Path = DEFAULT_RECOGNIZER_PATH,
) -> FaceEmbedder:
    global _face_embedder_instance
    if _face_embedder_instance is None:
        _face_embedder_instance = FaceEmbedder(
            detector_path=detector_path,
            recognizer_path=recognizer_path,
        )
    return _face_embedder_instance


__all__ = ["FaceEmbedder", "FaceDetection", "get_face_embedder"]
