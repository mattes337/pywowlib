"""
MPQ archive packer for WoW WotLK 3.3.5a patch files.

Collects generated WDT, ADT, and DBC files into the correct directory
structure for a WoW client patch MPQ. Attempts to create an actual MPQ
archive via StormLib if the creation API is available, otherwise falls
back to writing a plain directory tree that can be packed with external
MPQ tools (e.g. MPQ Editor, ladik's MPQEditor, or StormLib CLI).

MPQ internal paths follow WoW conventions:
    World\\Maps\\{MapName}\\{MapName}.wdt
    World\\Maps\\{MapName}\\{MapName}_{x}_{y}.adt
    DBFilesClient\\{name}.dbc
"""

import os
import shutil
import struct
import tempfile
import logging

log = logging.getLogger(__name__)

# Try to import the StormLib Python wrapper for MPQ creation.
# The existing pywowlib storm module only exposes read/extract functions;
# SFileCreateArchive and SFileAddFileEx are not yet wrapped. We attempt
# the import anyway so that future wrapper updates are picked up
# automatically.
_HAS_STORM_CREATE = False
try:
    from archives.mpq.native import storm

    # Probe for the archive creation function
    if hasattr(storm, 'SFileCreateArchive') and hasattr(storm, 'SFileAddFileEx'):
        _HAS_STORM_CREATE = True
except Exception:
    storm = None


# MPQ creation flags (from StormLib.h) used when StormLib is available.
_MPQ_CREATE_LISTFILE = 0x00100000
_MPQ_CREATE_ATTRIBUTES = 0x00200000
_MPQ_CREATE_ARCHIVE_V1 = 0x00000000  # MPQ v1 for WotLK compatibility

# File add flags
_MPQ_FILE_COMPRESS = 0x00000200
_MPQ_FILE_REPLACEEXISTING = 0x80000000

# Compression types
_MPQ_COMPRESSION_ZLIB = 0x00000002


class MPQPacker:
    """
    Collects files for MPQ archive creation.
    Generates the correct WoW patch directory structure.
    """

    def __init__(self, output_dir, patch_name="patch-4.MPQ"):
        """
        Args:
            output_dir: Base directory for output.
            patch_name: Name of the MPQ patch file.
        """
        self.output_dir = os.path.abspath(output_dir)
        self.patch_name = patch_name
        self.files = {}  # mpq_path -> bytes data

    def add_file(self, mpq_path, data):
        """
        Add a file to the MPQ archive.

        Args:
            mpq_path: Path within the MPQ archive.
                      Uses backslash separators per WoW convention,
                      e.g. "World\\Maps\\NewZone\\NewZone.wdt"
            data: bytes content of the file.

        Raises:
            TypeError: If data is not bytes.
        """
        if not isinstance(data, bytes):
            raise TypeError(
                "data must be bytes, got {}".format(type(data).__name__)
            )
        # Normalise to backslash (MPQ internal convention)
        mpq_path = mpq_path.replace("/", "\\")
        self.files[mpq_path] = data

    def add_wdt(self, map_name, wdt_data):
        """
        Add a WDT file with the correct MPQ path.

        Args:
            map_name: Map directory name (e.g. "MyCustomMap").
            wdt_data: bytes content of the WDT file.
        """
        mpq_path = "World\\Maps\\{}\\{}.wdt".format(map_name, map_name)
        self.add_file(mpq_path, wdt_data)

    def add_adt(self, map_name, tile_x, tile_y, adt_data):
        """
        Add an ADT tile file with the correct MPQ path.

        Args:
            map_name: Map directory name.
            tile_x:   Tile X coordinate (0..63).
            tile_y:   Tile Y coordinate (0..63).
            adt_data:  bytes content of the ADT file.
        """
        mpq_path = "World\\Maps\\{}\\{}_{:d}_{:d}.adt".format(
            map_name, map_name, tile_x, tile_y
        )
        self.add_file(mpq_path, adt_data)

    def add_dbc(self, dbc_name, dbc_data):
        """
        Add a DBC file with the correct MPQ path.

        The .dbc extension is appended automatically if not already present.

        Args:
            dbc_name: DBC file name (with or without .dbc extension).
            dbc_data: bytes content of the DBC file.
        """
        if not dbc_name.lower().endswith(".dbc"):
            dbc_name = dbc_name + ".dbc"
        mpq_path = "DBFilesClient\\{}".format(dbc_name)
        self.add_file(mpq_path, dbc_data)

    def build_directory(self):
        """
        Write all collected files to a directory structure that mirrors the
        internal MPQ layout. The output is ready for packing with external
        MPQ tools.

        Returns:
            str: Absolute path to the output directory root that contains
                 the World/ and DBFilesClient/ trees.
        """
        output_root = os.path.join(self.output_dir, "mpq_content")
        os.makedirs(output_root, exist_ok=True)

        for mpq_path, data in self.files.items():
            # Convert MPQ backslash paths to OS paths
            local_rel = mpq_path.replace("\\", os.sep)
            local_abs = os.path.join(output_root, local_rel)

            os.makedirs(os.path.dirname(local_abs), exist_ok=True)
            with open(local_abs, "wb") as fh:
                fh.write(data)
            log.info("Wrote %s (%d bytes)", local_abs, len(data))

        log.info(
            "Directory structure ready at %s (%d files)",
            output_root,
            len(self.files),
        )
        return output_root

    def build_mpq(self):
        """
        Attempt to create an actual MPQ archive using StormLib.

        If the StormLib Python wrapper exposes SFileCreateArchive and
        SFileAddFileEx, an MPQ file is written directly. Otherwise this
        method falls back to build_directory() and logs a warning.

        Returns:
            str: Absolute path to the created MPQ file, or to the
                 fallback directory if StormLib creation is unavailable.
        """
        if not _HAS_STORM_CREATE:
            log.warning(
                "StormLib archive creation API not available. "
                "Falling back to directory structure. "
                "Use an external MPQ tool to pack the output directory."
            )
            return self.build_directory()

        mpq_path = os.path.join(self.output_dir, self.patch_name)
        os.makedirs(self.output_dir, exist_ok=True)

        # Determine a safe max file count (power of 2, at least 16)
        max_files = max(16, len(self.files) * 2)
        power = 1
        while power < max_files:
            power <<= 1
        max_files = power

        create_flags = (
            _MPQ_CREATE_ARCHIVE_V1
            | _MPQ_CREATE_LISTFILE
            | _MPQ_CREATE_ATTRIBUTES
        )

        handle = None
        tmp_dir = None
        try:
            handle = storm.SFileCreateArchive(
                mpq_path, create_flags, max_files
            )

            # StormLib's SFileAddFileEx works with files on disk, so we
            # write each entry to a temp directory first.
            tmp_dir = tempfile.mkdtemp(prefix="mpqpacker_")

            for internal_path, data in self.files.items():
                tmp_file = os.path.join(
                    tmp_dir, internal_path.replace("\\", os.sep)
                )
                os.makedirs(os.path.dirname(tmp_file), exist_ok=True)
                with open(tmp_file, "wb") as fh:
                    fh.write(data)

                storm.SFileAddFileEx(
                    handle,
                    tmp_file,
                    internal_path,
                    _MPQ_FILE_COMPRESS | _MPQ_FILE_REPLACEEXISTING,
                    _MPQ_COMPRESSION_ZLIB,
                    _MPQ_COMPRESSION_ZLIB,
                )

            log.info(
                "Created MPQ archive %s (%d files)", mpq_path, len(self.files)
            )
        finally:
            if handle is not None:
                storm.SFileCloseArchive(handle)
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        return mpq_path


# ===========================================================================
# MPQ Extraction -- Read from existing MPQ archives
# ===========================================================================

# Try to import the MPQ read wrapper (StormLib-based).
_HAS_STORM = False
try:
    from archives.mpq import MPQFile
    _HAS_STORM = True
except Exception:
    MPQFile = None


class MPQExtractor:
    """
    Extract files from an existing MPQ archive.

    Uses the parent library MPQFile (StormLib wrapper) for reading.
    Provides convenience methods for listing, reading, and extracting
    game data files such as maps and DBC files.
    """

    def __init__(self, mpq_path):
        """
        Open an MPQ archive for reading.

        Args:
            mpq_path: Path to the MPQ archive file.

        Raises:
            RuntimeError: If StormLib is not available.
            FileNotFoundError: If the MPQ file does not exist.
        """
        if not _HAS_STORM:
            raise RuntimeError(
                "StormLib wrapper (archives.mpq.MPQFile) is not available. "
                "Cannot extract MPQ archives without native StormLib bindings."
            )

        if not os.path.isfile(mpq_path):
            raise FileNotFoundError(
                "MPQ file not found: {}".format(mpq_path)
            )

        self.mpq_path = os.path.abspath(mpq_path)
        self._mpq = MPQFile(self.mpq_path)
        log.info("Opened MPQ archive: %s", self.mpq_path)

    def close(self):
        """Close the MPQ archive."""
        if self._mpq is not None:
            self._mpq.close()
            self._mpq = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def list_files(self, pattern=None):
        """
        List files in the MPQ archive.

        Args:
            pattern: Optional fnmatch-style glob pattern to filter results.
                     Uses forward slashes for matching (MPQ paths are
                     normalised). Example: ``"World/Maps/*/*.adt"``

        Returns:
            list[str]: Sorted list of file paths within the archive.
                       Paths use forward slashes.
        """
        import fnmatch

        names = self._mpq.namelist()

        if pattern is not None:
            # Normalise pattern separators to forward slash
            pattern = pattern.replace("\\", "/")
            names = [n for n in names if fnmatch.fnmatch(n, pattern)]

        return sorted(names)

    def read_file(self, internal_path):
        """
        Read a file from the MPQ archive into memory.

        Args:
            internal_path: Path within the MPQ archive.
                           Accepts both forward and backslash separators.

        Returns:
            bytes: Raw file contents.

        Raises:
            KeyError: If the file is not found in the archive.
        """
        # MPQFile.read() expects backslash-separated paths internally
        normalised = internal_path.replace("/", "\\")
        return self._mpq.read(normalised)

    def extract_file(self, internal_path, output_path):
        """
        Extract a single file from the MPQ archive to disk.

        Args:
            internal_path: Path within the MPQ archive.
            output_path: Destination path on disk.

        Returns:
            str: Absolute path to the extracted file.

        Raises:
            KeyError: If the file is not found in the archive.
        """
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        data = self.read_file(internal_path)
        with open(output_path, 'wb') as fh:
            fh.write(data)

        log.info("Extracted %s -> %s (%d bytes)",
                 internal_path, output_path, len(data))
        return output_path

    def extract_map(self, map_name, output_dir):
        """
        Extract all files for a map (WDT + all ADTs).

        Searches for ``World/Maps/{map_name}/{map_name}.wdt`` and all
        matching ``{map_name}_*_*.adt`` files.

        Args:
            map_name: Map directory name (e.g. ``"Azeroth"``).
            output_dir: Base output directory. Files are written under
                        ``{output_dir}/World/Maps/{map_name}/``.

        Returns:
            dict: Mapping of internal MPQ path -> extracted disk path for
                  all successfully extracted files.
        """
        import fnmatch

        output_dir = os.path.abspath(output_dir)

        # Build pattern to match map files
        map_prefix = "World/Maps/{}/{}".format(map_name, map_name)
        all_files = self.list_files()

        extracted = {}

        for internal_path in all_files:
            normalised = internal_path.replace("\\", "/")
            is_wdt = normalised.lower() == "{}.wdt".format(map_prefix).lower()
            is_adt = (
                normalised.lower().startswith(
                    "World/Maps/{}/{}_".format(map_name, map_name).lower()
                )
                and normalised.lower().endswith(".adt")
            )

            if is_wdt or is_adt:
                rel_path = normalised.replace("/", os.sep)
                disk_path = os.path.join(output_dir, rel_path)
                try:
                    self.extract_file(internal_path, disk_path)
                    extracted[internal_path] = disk_path
                except Exception as exc:
                    log.warning("Failed to extract %s: %s",
                                internal_path, exc)

        log.info("Extracted %d map files for '%s' to %s",
                 len(extracted), map_name, output_dir)
        return extracted

    def extract_dbc(self, dbc_name, output_dir):
        """
        Extract a specific DBC file from the archive.

        Searches for ``DBFilesClient/{dbc_name}.dbc`` (the .dbc extension
        is appended automatically if not present).

        Args:
            dbc_name: DBC file name (with or without .dbc extension).
            output_dir: Output directory. File is written under
                        ``{output_dir}/DBFilesClient/``.

        Returns:
            str: Absolute path to the extracted DBC file.

        Raises:
            KeyError: If the DBC file is not found.
        """
        if not dbc_name.lower().endswith(".dbc"):
            dbc_name = dbc_name + ".dbc"

        internal_path = "DBFilesClient\\{}".format(dbc_name)
        rel_path = os.path.join("DBFilesClient", dbc_name)
        disk_path = os.path.join(os.path.abspath(output_dir), rel_path)

        return self.extract_file(internal_path, disk_path)


def extract_map(mpq_path, map_name, output_dir):
    """
    Convenience function to extract all map files from an MPQ archive.

    Opens the archive, extracts WDT + all ADTs for the given map name,
    and closes the archive.

    Args:
        mpq_path: Path to the MPQ archive.
        map_name: Map directory name (e.g. ``"Azeroth"``).
        output_dir: Base output directory.

    Returns:
        dict: Mapping of internal MPQ path -> extracted disk path.
    """
    with MPQExtractor(mpq_path) as extractor:
        return extractor.extract_map(map_name, output_dir)


def pack_map(output_dir, map_name, wdt_data, adt_files, dbc_files=None):
    """
    Convenience function to pack all map files into an MPQ structure.

    Args:
        output_dir: Output directory path.
        map_name:   Map directory name (e.g. "MyCustomMap").
        wdt_data:   bytes of the WDT file.
        adt_files:  dict mapping (x, y) tile coordinates to ADT bytes.
        dbc_files:  Optional dict mapping DBC name (str) to DBC bytes.

    Returns:
        str: Path to the output (MPQ file or directory).
    """
    packer = MPQPacker(output_dir)

    packer.add_wdt(map_name, wdt_data)

    for (tile_x, tile_y), adt_data in adt_files.items():
        packer.add_adt(map_name, tile_x, tile_y, adt_data)

    if dbc_files:
        for dbc_name, dbc_data in dbc_files.items():
            packer.add_dbc(dbc_name, dbc_data)

    return packer.build_mpq()
