**Repository:** alpibrusl/cancho
**Title:** A `Camera` capability beside `Tty`, so a cancho program can take frames without a foreign call

## Context

`docs/tty.md` made a serial port a capability and says, in its non-goals, that camera `ioctl` "is a measured question, not a commitment".
This is a measurement for it.

## What was done and measured (cancho-hdl branch `hardware-test-tang-nano-20k`)

A cancho program (`boards/tang-nano-20k/host/camfilter.cho`, compiler `471b8e93` built by cancho) streams greyscale frames from
standard input through an FPGA image filter over the `Tty` capability and writes the result. The frames come from **ffmpeg**, because
cancho cannot open the camera: the laptop webcam (`/dev/video0`, a UVC device, "LGE FHD Camera") reports raw YUYV 4:2:2 at
320x180, 320x240, 424x240, 640x360, 640x480 and larger, and MJPEG. 4 real frames in 5 filter modes matched an independent
implementation exactly (27,648 pixels per mode, 0 different).

## Why it is not just a library

* The kernel's UVC driver does not implement `read()`; capture needs `VIDIOC_S_FMT`, `REQBUFS`, `QUERYBUF`, `mmap`, `QBUF`, `STREAMON`
  and `DQBUF`. In cancho today that is `extern fn` for `ioctl`, `mmap`, `open` and `close`, with the V4L2 struct layouts written into the
  program per platform (the situation `docs/tty.md` §1 describes for serial).
* `cancho authority` would report those libc symbols one by one, and "never touches the filesystem" while opening a device node. For a
  robot, which camera a program can reach is exactly what the report should say.
* Not measured: whether a frame in an mmap'd buffer can be copied into a cancho slice without a further foreign call. I expect this is
  the hard part and have not tried it.

## Proposal

`res Camera` / `res Frame`, prefix-narrowed like `Tty` (`Camera("/dev/video0")`), with roughly: `camera_open`, `camera_configure(width,
height)` (YUYV or grey), `camera_next(&!Frame, into: &![byte])` that never blocks, `camera_close`, and `poller_add_camera`. Row in the
report: `camera_open("/dev/video0")`, `camera_read`. The backend owns the V4L2 numbers, as it owns the termios numbers for `Tty`.

## Open questions

* Pixel format vocabulary (one `int`, as for baud rates?) and whether the backend converts to grey.
* macOS (AVFoundation) is not a V4L2 story at all; Linux only first, as the first `Tty` slices were measured on one platform.
* Exposure and auto-focus controls: out of scope, or the same "one setting" discipline as `tty_configure`?

## Acceptance

A cancho program with no `extern fn` captures 100 frames from `/dev/video0` and `cancho authority` reports `camera_open("/dev/video0")` with
no foreign line. The cancho-hdl camera pipeline then drops ffmpeg.
