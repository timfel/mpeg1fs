#!/usr/bin/env python

import os
import sys
import errno
import subprocess

from fuse import FUSE, FuseOSError, Operations, fuse_get_context


class MpegTranscode(Operations):
    def __init__(self, root: str):
        self.root = root
        self.process: subprocess.Popen | None = None

    def _full_path(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]
        path = os.path.join(self.root, partial)
        return path

    def access(self, path, mode):
        full_path = self._full_path(path)
        if not os.access(full_path, mode):
            raise FuseOSError(errno.EACCES)

    def getattr(self, path, fh=None):
        full_path = self._full_path(path)
        st = os.lstat(full_path)
        return dict(
            (key, getattr(st, key))
            for key in (
                "st_atime",
                "st_ctime",
                "st_gid",
                "st_mode",
                "st_mtime",
                "st_nlink",
                "st_size",
                "st_uid",
            )
        )

    def readdir(self, path, fh):
        full_path = self._full_path(path)
        dirents = [".", ".."]
        if os.path.isdir(full_path):
            dirents.extend(
                [
                    e
                    for e in os.listdir(full_path)
                    if os.path.isdir(os.path.join(full_path, e))
                    or e.endswith(
                        (
                            "mp4",
                            "avi",
                            "mkv",
                            "mpg",
                            "mpeg",
                            "mov",
                            "wmv",
                            "flv",
                            "webm",
                        )
                    )
                ]
            )
        for r in dirents:
            yield r

    def readlink(self, path):
        pathname = os.readlink(self._full_path(path))
        if pathname.startswith("/"):
            # Path name is absolute, sanitize it.
            return os.path.relpath(pathname, self.root)
        else:
            return pathname

    def statfs(self, path):
        full_path = self._full_path(path)
        stv = os.statvfs(full_path)
        return dict(
            (key, getattr(stv, key))
            for key in (
                "f_bavail",
                "f_bfree",
                "f_blocks",
                "f_bsize",
                "f_favail",
                "f_ffree",
                "f_files",
                "f_flag",
                "f_frsize",
                "f_namemax",
            )
        )

    def utimens(self, path, times=None):
        return os.utime(self._full_path(path), times)

    def open(self, path, flags):
        if self.process:
            self.release(self, None, id(self.process))
        full_path = self._full_path(path)
        print(f"Opening {full_path=}")
        self.process = subprocess.Popen(
            [
                "/usr/bin/ffmpeg",
                "-i",
                full_path,
                "-f",
                "mpeg",
                "-vf",
                "scale=352:-1",
                "-c:v",
                "mpeg1video",
                "-b:v",
                "512k",
                "-c:a",
                "mp2",
                "-b:a",
                "64k",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-r",
                "24",
                "-preset",
                "ultrafast",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            text=False,
            bufsize=0,
        )
        return id(self.process)

    def read(self, path, length, offset, fh):
        result = b""
        while len(result) < length:
            result += os.read(self.process.stdout.fileno(), length - len(result))
        return result

    def release(self, path, fh):
        print(f"Releasing {fh=}")
        self.process.terminate()
        self.process = None


if __name__ == "__main__":
    root, mountpoint = sys.argv[1:3]
    FUSE(
        MpegTranscode(root),
        mountpoint,
        nothreads=True,
        foreground=True,
        allow_other=True,
    )
