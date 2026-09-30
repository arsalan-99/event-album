"""
FaceEmbedder — wraps OpenCV Zoo's YuNet (detection) + SFace (recognition).

Both model weights are Apache-2.0 licensed (opencv/opencv_zoo) — safe for
commercial use, unlike InsightFace/DeepFace's default pretrained weights.

Model files are NOT included here (they're binary, tracked via Git LFS in
the opencv_zoo repo). Run download_models.sh once to fetch them.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

import cv2
import numpy as np


@dataclass
class FaceDetection:
    bbox: tuple            # (x, y, w, h) in pixels
    landmarks: np.ndarray  # 5x2 array: right eye, left eye, nose tip, right mouth corner, left mouth corner
    confidence: float
    low_quality: bool      # True if bbox is smaller than MIN_FACE_SIZE


class FaceEmbedder:
    model_name = "sface"
    model_version = "2021dec"

    MIN_FACE_SIZE = 40  # px — below this, flag as low_quality rather than silently drop

    def __init__(
        self,
        detector_path: Union[str, Path],
        recognizer_path: Union[str, Path],
        score_threshold: float = 0.6,
        nms_threshold: float = 0.3,
    ):
        detector_path = str(Path(detector_path).resolve())
        recognizer_path = str(Path(recognizer_path).resolve())

        self._detector = cv2.FaceDetectorYN.create(
            model=detector_path,
            config="",
            input_size=(320, 320),  # resized internally to actual image size in detect()
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            top_k=5000,
        )
        self._recognizer = cv2.FaceRecognizerSF.create(
            model=recognizer_path,
            config="",
        )

    def detect(self, image: np.ndarray, max_edge: Optional[int] = 1280) -> List[FaceDetection]:
        """Detect all faces in a BGR image (as loaded by cv2.imread).
        
        If max_edge is set and the image's longest edge exceeds max_edge, the image
        is downscaled before running YuNet detection. Detected bounding boxes and
        landmarks are then rescaled back to the original-image coordinates, preserving
        sub-pixel alignment for subsequent full-resolution SFace alignCrop operations.
        MIN_FACE_SIZE filtering is strictly evaluated against original-resolution dimensions.
        """
        h, w = image.shape[:2]
        orig_max_edge = max(h, w)

        if max_edge and orig_max_edge > max_edge:
            scale = max_edge / float(orig_max_edge)
            dw, dh = int(round(w * scale)), int(round(h * scale))
            detect_image = cv2.resize(image, (dw, dh), interpolation=cv2.INTER_AREA)
        else:
            scale = 1.0
            detect_image = image
            dw, dh = w, h

        self._detector.setInputSize((dw, dh))
        _, faces = self._detector.detect(detect_image)

        results: List[FaceDetection] = []
        if faces is None:
            return results

        inv_scale = 1.0 / scale
        for face in faces:
            sx, sy, sbw, sbh = face[0:4]
            s_landmarks = face[4:14].reshape(5, 2)
            confidence = float(face[14])

            # Rescale back to original-resolution coordinates
            x = int(round(sx * inv_scale))
            y = int(round(sy * inv_scale))
            bw = int(round(sbw * inv_scale))
            bh = int(round(sbh * inv_scale))
            landmarks = s_landmarks * inv_scale

            results.append(
                FaceDetection(
                    bbox=(x, y, bw, bh),
                    landmarks=landmarks,
                    confidence=confidence,
                    low_quality=bw < self.MIN_FACE_SIZE or bh < self.MIN_FACE_SIZE,
                )
            )
        return results

    def embed(self, image: np.ndarray, detection: FaceDetection) -> np.ndarray:
        """Align + crop the face per `detection`, return a 128-d embedding."""
        # Reconstruct the raw detector row format SFace's alignCrop expects:
        # [x, y, w, h, 5x(landmark_x, landmark_y), score]
        face_row = np.array(
            [*detection.bbox, *detection.landmarks.flatten(), detection.confidence],
            dtype=np.float32,
        )
        aligned = self._recognizer.alignCrop(image, face_row)
        embedding = self._recognizer.feature(aligned)
        return embedding.flatten()

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        a_norm = a / np.linalg.norm(a)
        b_norm = b / np.linalg.norm(b)
        return float(np.dot(a_norm, b_norm))
