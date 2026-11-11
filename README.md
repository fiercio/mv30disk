# mv30disk

Verify floppy disk images from the **Roland MV-30 Studio-M** and list or extract the files stored on them.

The script is meant for people archiving MV-30 floppies with a flux-level reader such as [Greaseweazle](https://github.com/keirf/greaseweazle). It tells you whether a dump is complete and, if it is not, exactly which files are affected.

## The MV-30 disk format

An MV-30 disk is a 3.5" double-density (720 KB) floppy with a standard IBM MFM track layout:

| Property | Value |
|---|---|
| Cylinders | 80 |
| Sides | 2 |
| Sectors per track | 9 |
| Sector size | 512 bytes |
| Image size | 737,280 bytes |

A raw sector image of such a disk (`.img`, `.dsk`, `.ima`) is simply all sectors in order, cylinder by cylinder, side 0 before side 1.

The file system is **FAT12 without a BIOS Parameter Block**. Sector 0 holds a Roland text header instead of a DOS boot sector, which is why modern operating systems refuse to mount these disks. The layout itself is the same as on a 720 KB DOS disk:

| Sectors | Content |
|---|---|
| 0 | Roland header; the text `MV-30` starts at byte 4 |
| 1–3 | FAT, first copy (begins with `F9 FF FF`) |
| 4–6 | FAT, second copy |
| 7–13 | Root directory (112 entries of 32 bytes) |
| 14–1439 | Data area; one cluster is 2 sectors (1024 bytes) |

Directory entries use the usual FAT 8.3 format, including subdirectories. A system disk contains:

```
MV30.SYS        operating system
CONFIG.MV3
CHAINPLY.MV3
SOUND.PRM
SONG.DIR
SONG/           directory with SONGnn.DAT files
```

> **Note:** this layout was worked out from system disk images (versions from 1990 and 1992). Data-only disks are expected to follow it but have not been checked.

## What the script does

`mv30disk.py` reads a raw sector image and:

- checks that the size is exactly 737,280 bytes,
- checks the Roland header, the FAT signature and that both FAT copies match,
- finds sectors that Greaseweazle could not read (it fills them with the text `-=[BAD SECTOR]=-`) and reports their track, side and sector,
- lists all files and directories, flagging files with a broken FAT chain or an unread sector,
- optionally extracts all files to a directory.

It never modifies the image. The exit code is `0` when the image looks correct, `1` when a problem was found and `2` when the file cannot be read.

Messages are printed in English or Polish depending on the system locale, with English as the default. Use `--lang` to override.

## Requirements

Python 3.8 or newer. No third-party packages.

## Usage

```
python3 mv30disk.py IMAGE [-x DIR] [--lang {en,pl}]
```

| Option | Meaning |
|---|---|
| `IMAGE` | disk image file (`.img`, `.dsk`) |
| `-x DIR`, `--extract DIR` | extract all files into `DIR` |
| `--lang {en,pl}` | force the message language |
| `--version` | print the version |
| `-h`, `--help` | print help |

Check an image and list its files:

```
$ python3 mv30disk.py disk01.img
Size: 737280 bytes (OK)
Sector 0 header: 'MV-30   '
FAT signature (F9 FF FF): OK
Both FAT copies match: OK
Sectors not read by Greaseweazle: 0
Files:
  MV30.SYS                       154624
  CONFIG.MV3                          4
  CHAINPLY.MV3                      256
  SOUND.PRM                       69808
  SONG.DIR                         2048
  [dir] SONG/
  SONG/SONG63.DAT                 43008
  ...

Result: the image looks correct.
```

A dump with read errors looks like this:

```
Sectors not read by Greaseweazle: 3
  track 17, side 1, sector 4  (cluster 154)
  track 17, side 1, sector 5  (cluster 154)
  track 65, side 1, sector 5  (cluster 586)
Files:
  ...
  CHAINPLY.MV3                      256   <-- CONTAINS AN UNREAD SECTOR
  ...
  SONG/SONG55.DAT                 29184   <-- CONTAINS AN UNREAD SECTOR

Result: the image does NOT look like a correct MV-30 dump.
```

Extract the files:

```
python3 mv30disk.py disk01.img -x disk01_files
```

## Reading an MV-30 disk with Greaseweazle

Connect an ordinary 3.5" PC floppy drive to the Greaseweazle and read the disk as a 720 KB IBM disk:

```
gw read --format=ibm.720 --retries=10 disk01.img
```

Every track should report `9/9 sectors`. A line such as `Giving up: 3 sectors missing` means the image has holes; check it with `mv30disk.py` to see what was lost.

To retry only the tracks that failed, for example cylinders 17 and 65 on side 1:

```
gw read --format=ibm.720 --retries=20 --tracks="c=17,65:h=1" test.img
```

To write an image back to a floppy:

```
gw write --format=ibm.720 disk01.img
```

### High-density disks: cover the HD hole

The MV-30 drive is double-density only and ignores the density hole, so it happily records 720 KB data on HD (1.44 MB) media. A PC drive does look at the hole: it detects an HD disk and switches its read circuitry to HD mode, and the DD recording then reads back with many errors.

If a disk has the HD hole (the one without a slider, opposite the write-protect tab), **cover it with opaque tape on both sides before reading**. Do the same when writing images back to HD media for use in the MV-30.

DD recordings on HD media are weaker and age worse, so some sectors may stay marginal even with the hole covered. More retries, re-inserting the disk or trying a different drive often helps.

### Other troubleshooting hints

- One side reads perfectly and the other barely at all: suspect a dirty or faulty drive head. Clean the heads or try another drive.
- `Seek: Track 0 not found` together with `No Index`: the drive is not responding at all. Check power, the ribbon cable and the drive select (`--drive=a` or `--drive=b`).

## Using the images

A complete raw image can be loaded in the MV-30 from a Gotek floppy emulator running [FlashFloppy](https://github.com/keirf/flashfloppy), or written back to a real floppy.

## Limitations

- Read-only: the script does not create, repair or modify images.
- Only raw sector images are supported, not flux (`.scp`) or track (`.hfe`) formats.
- The contents of the files themselves (songs, sounds) are not interpreted.
