# A FUSE Filesystem for streaming MPEG1 video and Youtube to my Amiga

I got unhappy that my PiStormed Amiga has fast network and CPU, but I cannot just go and stream videos on my NAS or from YouTube (yes, AmiTube exists, but then I have to wait for the video to load).

This is a simple script I can run on my Linux box to mount a couple of virtual filesystems in a Samba + FTP shared folder that the Amiga can access.

I mount my videos like this:
```
mpeg1fs /media/usbdisk/videos /samba/mpegvideos
```

Now on the Amiga I have SMB0: mounted, and can just browse the `mpegvideos` folder with the Riva requester and open any video, regardless of filetype.
The FUSE filesystem transparently serves it as MPEG1 that Riva can play.

I mount youtube like this:
```
mpeg1fs --create-on-navigation /samba/youtube
```

In the file requester (or the shell, or DOpus or whatever) the youtube folder looks initially empty.
I now just `cd` folder names that don't exist (or type them at the bottom of the Riva file requester).
The FUSE server just creates those virtually, the names are actually used as search string for YouTube.
It takes a few seconds to populate, so you'll have to refresh the requester after a bit.
It shows a few Videos.
To narrow down the search, add subfolders, then another search starts with the parent and subfolder name together.
Click any video, it starts streaming after a few seconds of buffering.

Nothing is stored on the Linux server, it's all in memory and streamed only as fast as the Amiga consumes it.
So it only needs to run ffmpeg fast enough to convert at 1x speed, which even my Raspberry Pi 0 can handle.

So there.
I'm off to watch the entire Amigos Amigathon on my Amiga.
