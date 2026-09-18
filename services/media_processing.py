"""Local worker-side media inspection helpers for OSS-backed assets."""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
from typing import Optional


def image_dimensions(path: str, mime: str) -> tuple[Optional[int], Optional[int]]:
    try:
        with open(path, "rb") as stream:
            header = stream.read(32)
            if mime == "image/png" and header[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", header[16:24])
            if mime == "image/gif" and header[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", header[6:10])
            if mime in {"image/jpeg", "image/jpg"} and header[:2] == b"\xff\xd8":
                stream.seek(2)
                while True:
                    if stream.read(1) != b"\xff":
                        continue
                    marker = stream.read(1)
                    while marker == b"\xff":
                        marker = stream.read(1)
                    if marker in {b"\xd8", b"\xd9"}:
                        continue
                    length_bytes = stream.read(2)
                    if len(length_bytes) != 2:
                        break
                    length = struct.unpack(">H", length_bytes)[0]
                    if marker[0] in set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0)):
                        data = stream.read(5)
                        return struct.unpack(">HH", data[1:5])
                    stream.seek(max(length - 2, 0), 1)
    except (OSError, struct.error, IndexError):
        pass
    return None, None


def video_metadata(path: str) -> tuple[Optional[int], Optional[int], Optional[float]]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None, None, None
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=width,height,duration", "-of", "json", path], capture_output=True, text=True, timeout=30, check=True)
        streams = json.loads(result.stdout).get("streams") or []
        video = next((item for item in streams if item.get("width") and item.get("height")), None)
        if not video:
            return None, None, None
        return int(video["width"]), int(video["height"]), float(video["duration"]) if video.get("duration") else None
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, json.JSONDecodeError):
        return None, None, None


def generate_video_cover(source: str, target: str) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        subprocess.run([ffmpeg, "-y", "-ss", "00:00:01", "-i", source, "-frames:v", "1", "-q:v", "3", target], capture_output=True, timeout=60, check=True)
        return os.path.isfile(target) and os.path.getsize(target) > 0
    except (OSError, subprocess.SubprocessError):
        return False


def generate_thumbnail(source: str, target: str, asset_type: str) -> bool:
    """Generate a small preview using ffmpeg when available."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    seek = ["-ss", "00:00:01"] if asset_type == "video" else []
    try:
        subprocess.run(
            [ffmpeg, "-y", *seek, "-i", source, "-vf", "scale=480:-2", "-frames:v", "1", "-q:v", "5", target],
            capture_output=True, timeout=60, check=True,
        )
        return os.path.isfile(target) and os.path.getsize(target) > 0
    except (OSError, subprocess.SubprocessError):
        return False
