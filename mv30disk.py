#!/usr/bin/env python3
"""Verify Roland MV-30 floppy disk images and list or extract their files.

An MV-30 disk is a 720 KB double-density floppy holding a FAT12 file system
whose boot sector lacks the BIOS Parameter Block, so ordinary tools refuse to
mount it. This script uses the fixed layout instead.
"""
import argparse
import locale
import os
import sys

__version__ = "1.0.0"

SECTOR = 512
IMAGE_SIZE = 80 * 2 * 9 * SECTOR      # 737,280 bytes
SECTORS_PER_TRACK = 9
HEADS = 2
FAT_START = 1                         # first FAT copy starts at sector 1
FAT_SECTORS = 3                       # two copies, 3 sectors each
ROOT_START = 7                        # root directory: sectors 7-13
ROOT_ENTRIES = 112
DATA_START = 14                       # cluster 2 starts here
CLUSTER = 2 * SECTOR                  # 2 sectors per cluster
BAD_MARKER = b"-=[BAD SECTOR]=-"      # written by Greaseweazle for unread sectors

MESSAGES = {
    "en": {
        "description": "Verify a Roland MV-30 disk image (720 KB) and list or extract its files.",
        "arg_image": "disk image file (.img, .dsk)",
        "arg_extract": "extract all files into directory DIR",
        "arg_lang": "message language (default: from system locale, falling back to English)",
        "cannot_read": "Cannot read {path}: {err}",
        "too_small": "File is too small to be a 720 KB sector image.",
        "size": "Size: {size} bytes",
        "size_ok": "OK",
        "size_bad": "WRONG, expected {expected}",
        "header": "Sector 0 header: {text!r}",
        "fat_sig": "FAT signature (F9 FF FF): {result}",
        "fat_match": "Both FAT copies match: {result}",
        "ok": "OK",
        "bad": "BAD ({detail})",
        "no": "NO",
        "unread": "Sectors not read by Greaseweazle: {count}",
        "unread_at": "  track {cyl}, side {head}, sector {sec}",
        "unread_cluster": "  (cluster {cluster})",
        "unread_system": "  (system area!)",
        "files": "Files:",
        "label": "  volume label: {label!r}",
        "dir": "  [dir] {path}/",
        "flag_chain": "   <-- BROKEN FAT CHAIN",
        "flag_unread": "   <-- CONTAINS AN UNREAD SECTOR",
        "extracted": "Files extracted to: {path}",
        "result_ok": "Result: the image looks correct.",
        "result_bad": "Result: the image does NOT look like a correct MV-30 dump.",
    },
    "pl": {
        "description": "Sprawdza obraz dyskietki Roland MV-30 (720 KB) i wypisuje lub wypakowuje pliki.",
        "arg_image": "plik obrazu dyskietki (.img, .dsk)",
        "arg_extract": "wypakuj wszystkie pliki do katalogu DIR",
        "arg_lang": "język komunikatów (domyślnie: z ustawień systemu, w razie braku angielski)",
        "cannot_read": "Nie można odczytać {path}: {err}",
        "too_small": "Plik jest za mały na obraz sektorowy 720 KB.",
        "size": "Rozmiar: {size} B",
        "size_ok": "OK",
        "size_bad": "ŹLE, powinno być {expected}",
        "header": "Nagłówek sektora 0: {text!r}",
        "fat_sig": "Sygnatura FAT (F9 FF FF): {result}",
        "fat_match": "Obie kopie FAT zgodne: {result}",
        "ok": "OK",
        "bad": "ŹLE ({detail})",
        "no": "NIE",
        "unread": "Sektory nieodczytane przez Greaseweazle: {count}",
        "unread_at": "  ścieżka {cyl}, strona {head}, sektor {sec}",
        "unread_cluster": "  (klaster {cluster})",
        "unread_system": "  (obszar systemowy!)",
        "files": "Pliki:",
        "label": "  etykieta: {label!r}",
        "dir": "  [katalog] {path}/",
        "flag_chain": "   <-- USZKODZONY ŁAŃCUCH FAT",
        "flag_unread": "   <-- ZAWIERA NIEODCZYTANY SEKTOR",
        "extracted": "Pliki wypakowane do: {path}",
        "result_ok": "Wynik: obraz wygląda poprawnie.",
        "result_bad": "Wynik: obraz NIE wygląda na poprawny zrzut MV-30.",
    },
}


def detect_language():
    """Pick the message language from the system locale; English by default."""
    candidates = [os.environ.get(v, "") for v in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")]
    try:
        candidates.append(locale.getlocale()[0] or "")
    except (ValueError, TypeError):
        pass
    for value in candidates:
        value = value.strip().lower()
        if not value:
            continue
        # e.g. "pl_PL.UTF-8", "pl", "pl:en" (LANGUAGE) or "Polish_Poland" (Windows)
        return "pl" if value.startswith(("pl", "polish")) else "en"
    return "en"


class Image:
    def __init__(self, data):
        self.data = data
        self.fat = self.sectors(FAT_START, FAT_SECTORS)
        self.fat_copy = self.sectors(FAT_START + FAT_SECTORS, FAT_SECTORS)
        self.bad_sectors = [
            lba for lba in range(len(data) // SECTOR)
            if BAD_MARKER in self.sectors(lba, 1)
        ]
        self.bad_clusters = {
            (lba - DATA_START) // 2 + 2 for lba in self.bad_sectors if lba >= DATA_START
        }

    def sectors(self, lba, count):
        return self.data[lba * SECTOR:(lba + count) * SECTOR]

    def fat_entry(self, n):
        offset = n * 3 // 2
        if offset + 1 >= len(self.fat):
            return 0xFFF
        value = self.fat[offset] | (self.fat[offset + 1] << 8)
        return (value >> 4) if n & 1 else (value & 0xFFF)

    def chain(self, start):
        clusters, seen = [], set()
        cluster = start
        while 2 <= cluster < 0xFF0 and cluster not in seen:
            seen.add(cluster)
            clusters.append(cluster)
            cluster = self.fat_entry(cluster)
        return clusters

    def read_chain(self, start):
        return b"".join(
            self.sectors(DATA_START + (c - 2) * 2, 2) for c in self.chain(start)
        )

    def root_directory(self):
        return self.data[
            ROOT_START * SECTOR:ROOT_START * SECTOR + ROOT_ENTRIES * 32
        ]


def directory_entries(raw):
    for i in range(0, len(raw) - 31, 32):
        entry = raw[i:i + 32]
        if entry[0] == 0x00:
            break
        if entry[0] == 0xE5:
            continue
        yield {
            "name": entry[0:8].decode("latin-1").rstrip(),
            "ext": entry[8:11].decode("latin-1").rstrip(),
            "attr": entry[11],
            "start": entry[26] | (entry[27] << 8),
            "size": int.from_bytes(entry[28:32], "little"),
        }


def safe_name(name):
    return "".join(ch if ch.isprintable() and ch not in '/\\:*?"<>|' else "_" for ch in name)


def walk(image, raw, path, outdir, msg):
    for entry in directory_entries(raw):
        if entry["name"] in (".", ".."):
            continue
        if entry["attr"] & 0x08:                      # volume label
            label = (entry["name"] + entry["ext"]).strip()
            if label:
                print(msg["label"].format(label=label))
            continue
        name = safe_name(entry["name"] + ("." + entry["ext"] if entry["ext"] else ""))
        full = path + name
        if entry["attr"] & 0x10:                      # subdirectory
            print(msg["dir"].format(path=full))
            if outdir:
                os.makedirs(os.path.join(outdir, full), exist_ok=True)
            walk(image, image.read_chain(entry["start"]), full + "/", outdir, msg)
            continue
        data = image.read_chain(entry["start"])[:entry["size"]]
        flags = ""
        if len(data) != entry["size"]:
            flags += msg["flag_chain"]
        if image.bad_clusters & set(image.chain(entry["start"])):
            flags += msg["flag_unread"]
        print(f"  {full:<28} {entry['size']:>8}{flags}")
        if outdir:
            with open(os.path.join(outdir, full), "wb") as handle:
                handle.write(data)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    # The language has to be known before argparse builds its help text.
    lang = detect_language()
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv) and argv[i + 1] in MESSAGES:
            lang = argv[i + 1]
        elif arg.startswith("--lang=") and arg[7:] in MESSAGES:
            lang = arg[7:]
    msg = MESSAGES[lang]

    parser = argparse.ArgumentParser(description=msg["description"])
    parser.add_argument("image", help=msg["arg_image"])
    parser.add_argument("-x", "--extract", metavar="DIR", help=msg["arg_extract"])
    parser.add_argument("--lang", choices=sorted(MESSAGES), help=msg["arg_lang"])
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    try:
        with open(args.image, "rb") as handle:
            data = handle.read()
    except OSError as err:
        print(msg["cannot_read"].format(path=args.image, err=err.strerror), file=sys.stderr)
        return 2

    ok = len(data) == IMAGE_SIZE
    verdict = msg["size_ok"] if ok else msg["size_bad"].format(expected=IMAGE_SIZE)
    print(msg["size"].format(size=len(data)), f"({verdict})")
    if len(data) < DATA_START * SECTOR:
        print(msg["too_small"], file=sys.stderr)
        return 1

    image = Image(data)
    print(msg["header"].format(text=data[4:12].decode("latin-1")))

    signature_ok = image.fat[:3] == b"\xf9\xff\xff"
    print(msg["fat_sig"].format(
        result=msg["ok"] if signature_ok else msg["bad"].format(detail=image.fat[:3].hex(" "))))
    fats_match = image.fat == image.fat_copy
    print(msg["fat_match"].format(result=msg["ok"] if fats_match else msg["no"]))

    print(msg["unread"].format(count=len(image.bad_sectors)))
    for lba in image.bad_sectors:
        where = msg["unread_at"].format(
            cyl=lba // (SECTORS_PER_TRACK * HEADS),
            head=(lba % (SECTORS_PER_TRACK * HEADS)) // SECTORS_PER_TRACK,
            sec=lba % SECTORS_PER_TRACK + 1,
        )
        if lba >= DATA_START:
            where += msg["unread_cluster"].format(cluster=(lba - DATA_START) // 2 + 2)
        else:
            where += msg["unread_system"]
        print(where)

    print(msg["files"])
    if args.extract:
        os.makedirs(args.extract, exist_ok=True)
    walk(image, image.root_directory(), "", args.extract, msg)
    if args.extract:
        print(msg["extracted"].format(path=args.extract))

    ok = ok and signature_ok and fats_match and not image.bad_sectors
    print()
    print(msg["result_ok"] if ok else msg["result_bad"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
