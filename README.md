# SD card cloning on Ubuntu (RPi Ubuntu 24.04 image)

This is a safe, repeatable workflow to clone a Raspberry Pi SD card on an
Ubuntu laptop with a built-in SD card reader. These steps create a master
image once and then write it to each target card.

## Notes and constraints

- Target SD cards must be the same size or larger than the source card.
- `dd` is destructive. Double-check device paths before you run it.
- Keep the source card unmounted while imaging.

## 1) Identify the source device

Insert the **source** card and list block devices:

- `lsblk -o NAME,SIZE,MODEL,FSTYPE,MOUNTPOINT`

Pick the full device path (example: `/dev/sdb`). Do not use a partition path
like `/dev/sdb1`.

## 2) Unmount the source card

Unmount any mounted partitions from the source card:

- `sudo umount /dev/sdX*`

Replace `sdX` with your source device.

## 3) Create a master image

Create a raw image file from the source card:

- `sudo dd if=/dev/sdX of=~/rpi-ubuntu-24.img bs=4M status=progress conv=fsync`
- `sync`

Optionally compress to save space:

- `sudo dd if=/dev/sdX bs=4M status=progress | gzip -1 > ~/rpi-ubuntu-24.img.gz`

## 4) Write the image to each target card

Insert a **target** card, then write the image:

- `sudo dd if=~/rpi-ubuntu-24.img of=/dev/sdY bs=4M status=progress conv=fsync`
- `sync`

Power off the card so it is safe to remove:

- `udisksctl power-off -b /dev/sdY`

Repeat this step for each of your six target cards.

## 4b) Using Raspberry Pi Imager (optional)

Raspberry Pi Imager can write your `rpi-ubuntu-24.img` file and shows progress
as it writes and verifies each card. It does not monitor a `dd` run, so use it
only after you have created the master image in step 3.

## 5) Optional verification (recommended)

This reads the whole card back and compares it to the image:

- `sudo cmp --bytes=$(stat -c%s ~/rpi-ubuntu-24.img) /dev/sdY ~/rpi-ubuntu-24.img`

## 6) First boot on a larger card

If a target card is larger than the source, expand the root filesystem on
first boot. On Ubuntu for Raspberry Pi, `cloud-init` or `growpart` usually
handles this automatically, but verify free space with `df -h`.
