#!/usr/bin/env python

import os
import select
import shutil
import sys
import errno
import subprocess
import stat
import time
from typing import IO

from fuse import FUSE, FuseOSError, Operations
from yt_dlp import YoutubeDL


def _ffmpeg_command(full_path):
    return [
        shutil.which("ffmpeg"),
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
    ]


def _read_pipe(fh: IO, length, timeout=30):
    result = b""
    t0 = time.time()
    while len(result) < length and time.time() - t0 < timeout:
        if select.select([fh], [], [], timeout)[0]:
            result += os.read(fh.fileno(), length - len(result))
        else:
            print("Read timed out")
            break
    return result


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
            _ffmpeg_command(full_path),
            stdout=subprocess.PIPE,
            text=False,
            bufsize=0,
        )
        return id(self.process)

    def read(self, path, length, offset, fh):
        return _read_pipe(self.process.stdout, length, timeout=1)

    def release(self, path, fh):
        self.process.terminate()
        self.process = None


class YTFS(Operations):
    YDL_OPTIONS = {"noplaylist": "True"}
    NUMBER_OF_VIDEOS = 10
    VIDEOS_KEY = 0
    SEARCH_KEY = 1

    def __init__(self, create_on_navigation=False):
        self.process: subprocess.Popen | None = None
        self.ytprocess: subprocess.Popen | None = None
        self.directories = {self.VIDEOS_KEY: {}, self.SEARCH_KEY: ""}
        self.create_on_navigation = create_on_navigation

    def _ascii(self, s):
        return "".join(c if ord(c) < 128 else "-" for c in s)

    def _search(self, root, head):
        search = " ".join([root[self.SEARCH_KEY], head])
        root[head] = {self.SEARCH_KEY: search}
        with YoutubeDL(self.YDL_OPTIONS) as ydl:
            videos = ydl.extract_info(f"ytsearch:{search}", download=False)["entries"][
                0 : self.NUMBER_OF_VIDEOS
            ]
            root[head][self.VIDEOS_KEY] = {
                self._ascii(entry["title"]): entry for entry in videos
            }

    def _find_directory(self, path) -> tuple[str, str | None, list[str] | None]:
        if path.startswith("/"):
            path = path[1:]
        root = self.directories
        head, *tail = path.split("/")
        while head in root and tail:
            root = root[head]
            head = tail[0]
            tail = tail[1:]
        return (root, head, tail)

    def mkdir(self, path, mode):
        root, head, tail = self._find_directory(path)
        if tail:
            raise FuseOSError(errno.ENOENT)
        if head in root:
            raise FuseOSError(errno.EEXIST)
        self._search(root, head)

    def access(self, path, mode):
        root, head, tail = self._find_directory(path)
        if head and head not in root and head not in root[self.VIDEOS_KEY]:
            raise FuseOSError(errno.ENOENT)

    def getattr(self, path, fh=None):
        root, head, tail = self._find_directory(path)
        if head in root[self.VIDEOS_KEY]:
            return dict(
                st_atime=0,
                st_ctime=0,
                st_gid=os.getgid(),
                st_mode=(stat.S_IFREG | 0o777),
                st_mtime=0,
                st_nlink=1,
                st_size=2**30,
                st_uid=os.getuid(),
            )
        if head in root or not head:
            root = root[head] if head else root
            return dict(
                st_atime=0,
                st_ctime=0,
                st_gid=os.getgid(),
                st_mode=(stat.S_IFDIR | 0o777),
                st_mtime=0,
                st_nlink=len(root.keys()),
                st_size=0,
                st_uid=os.getuid(),
            )
        if self.create_on_navigation:
            self.mkdir(path, 0o777)
            return self.getattr(path)
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)

    def getxattr(self, path, name, position=0):
        self.getattr(path)  # for the exception
        return b""

    def readdir(self, path, fh):
        root, head, _ = self._find_directory(path)
        if head and head not in root:
            raise FuseOSError(errno.ENOENT)
        root = root[head] if head else root
        dirents = [".", ".."]
        dirents.extend(k for k in root.keys() if isinstance(k, str))
        dirents.extend(k for k in root.get(0, {}).keys() if isinstance(k, str))
        for r in dirents:
            yield r

    def open(self, path, flags):
        if self.process:
            self.release(self, None, id(self.process))
        root, head, _ = self._find_directory(path)
        if head in root:
            raise FuseOSError(errno.EACCES)
        video = root[self.VIDEOS_KEY].get(head)
        if not video:
            raise FuseOSError(errno.ENOENT)
        print(f"Opening {video['title']=}")
        url = video["webpage_url"]
        self.ytprocess = subprocess.Popen(
            [
                os.path.join(os.path.dirname(sys.executable), "yt-dlp"),
                "-f",
                "w",
                url,
                "-o",
                "-",
            ],
            stdout=subprocess.PIPE,
            text=False,
            bufsize=2**18,
        )
        self.process = subprocess.Popen(
            _ffmpeg_command("pipe:0"),
            stdin=self.ytprocess.stdout,
            stdout=subprocess.PIPE,
            text=False,
            bufsize=0,
        )
        self.ytprocess.stdout.close()  # enable write error in ytdl if ffmpeg dies
        return id(self.process)

    def read(self, path, length, offset, fh):
        return _read_pipe(self.process.stdout, length, timeout=15)

    def release(self, path, fh):
        self.ytprocess.terminate()
        self.ytprocess = None
        self.process.terminate()
        self.process = None


if __name__ == "__main__":
    from argparse import ArgumentParser

    parser = ArgumentParser(
        description="Mount a filesystem with MPEG transcoding and YouTube search capabilities."
    )
    parser.add_argument(
        "source_dir",
        nargs="?",
        help="Source directory to mount. If none given, we mount YouTube",
        default=None,
    )
    parser.add_argument("target_dir", help="Target directory to mount the filesystem")
    parser.add_argument(
        "-d", "--debug", action="store_true", help="Enable debug output"
    )
    parser.add_argument(
        "-f", "--foreground", action="store_true", help="Run in foreground"
    )
    parser.add_argument(
        "--create-on-navigation",
        action="store_true",
        help="Create YouTube directions on navigation (without explicit mkdir).",
    )
    args = parser.parse_args()

    if args.debug:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    if args.source_dir is None:
        FUSE(
            YTFS(create_on_navigation=args.create_on_navigation),
            args.target_dir,
            debug=args.debug,
            nothreads=True,
            foreground=args.foreground,
            allow_other=True,
        )
    else:
        FUSE(
            MpegTranscode(args.source_dir),
            args.target_dir,
            debug=args.debug,
            nothreads=True,
            foreground=args.foreground,
            allow_other=True,
        )
