#!/usr/bin/env python
"""
Pure-Python MPQ v1 archive tool for WoW WotLK 3.3.5a patch files.

Creates, reads, and extracts MPQ v1 archives without requiring the StormLib
native extension. Files are stored uncompressed as single units.

Usage:
  python tools/mpq_packer.py create <output.mpq> --dir <content_dir>
  python tools/mpq_packer.py create <output.mpq> --add <path_in_mpq>:<local_file> ...
  python tools/mpq_packer.py info <archive.mpq>
  python tools/mpq_packer.py list <archive.mpq> [--pattern "*.adt"]
  python tools/mpq_packer.py extract <archive.mpq> [-o output_dir] [--file <path>]
"""

import struct
import os
import sys
import argparse
import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MPQ encryption / hash table
# ---------------------------------------------------------------------------

def _init_crypt_table():
    """Initialize the MPQ encryption/hash table (1280 entries)."""
    table = [0] * 1280
    seed = 0x00100001
    for index1 in range(256):
        index2 = index1
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp1 = (seed & 0xFFFF) << 0x10
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp2 = seed & 0xFFFF
            table[index2] = temp1 | temp2
            index2 += 256
    return table


CRYPT_TABLE = _init_crypt_table()


def _hash_string(string, hash_type):
    """
    Compute MPQ hash for a filename.

    Args:
        string: Filename (internal MPQ path). Hashed case-insensitively.
        hash_type:
            0 = HASH_TABLE_INDEX (position in hash table)
            1 = HASH_NAME_A (first name hash for verification)
            2 = HASH_NAME_B (second name hash for verification)
            3 = HASH_FILE_KEY (encryption key, not needed for unencrypted)

    Returns:
        int: 32-bit hash value.
    """
    seed1 = 0x7FED7FED
    seed2 = 0xEEEEEEEE

    for ch in string.upper():
        value = ord(ch)
        seed1 = CRYPT_TABLE[hash_type * 256 + value] ^ ((seed1 + seed2) & 0xFFFFFFFF)
        seed2 = (value + seed1 + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF

    return seed1 & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# MPQ constants
# ---------------------------------------------------------------------------

_MPQ_MAGIC = b'MPQ\x1a'
_MPQ_HEADER_SIZE = 32
_MPQ_FORMAT_V1 = 0
_SECTOR_SIZE_SHIFT = 3  # sector_size = 512 << 3 = 4096

# Block table flags
_FILE_EXISTS = 0x80000000
_FILE_SINGLE_UNIT = 0x04000000
_FILE_FLAGS = _FILE_EXISTS | _FILE_SINGLE_UNIT  # 0x84000000

# Hash table sentinel values
_HASH_ENTRY_EMPTY = 0xFFFFFFFF
_HASH_LOCALE_NEUTRAL = 0xFFFF
_HASH_PLATFORM_DEFAULT = 0


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _next_power_of_2(n):
    """Return the smallest power of 2 >= n."""
    if n <= 0:
        return 1
    power = 1
    while power < n:
        power <<= 1
    return power


# ---------------------------------------------------------------------------
# PurePythonMPQWriter
# ---------------------------------------------------------------------------

class PurePythonMPQWriter:
    """
    Creates MPQ v1 archives in pure Python.

    Files are stored uncompressed as single units (FILE_EXISTS | FILE_SINGLE_UNIT).
    The hash table is sized to the next power of 2 >= (file_count * 2) with
    a minimum of 16 entries.
    """

    def __init__(self):
        self.files = {}  # internal_path -> bytes

    def add_file(self, internal_path, data):
        """
        Add a file to the archive.

        Args:
            internal_path: MPQ-style path (backslash separators preferred).
                           Forward slashes are normalised automatically.
            data: File content as bytes.

        Raises:
            TypeError: If data is not bytes.
        """
        if not isinstance(data, bytes):
            raise TypeError(
                "data must be bytes, got {}".format(type(data).__name__)
            )
        # Normalise to backslash (MPQ internal convention)
        internal_path = internal_path.replace('/', '\\')
        self.files[internal_path] = data

    def write(self, output_path):
        """
        Write the MPQ v1 archive to disk.

        Layout:
            [Header 32 bytes]
            [File data blocks]
            [Hash table]
            [Block table]

        Args:
            output_path: Destination file path for the MPQ archive.

        Returns:
            str: Absolute path to the written archive.
        """
        # Build the (listfile) and include it as a file in the archive
        all_paths = sorted(self.files.keys())
        listfile_content = "\r\n".join(all_paths).encode('utf-8')

        # Ordered list of files to write: user files + (listfile)
        write_order = []
        for path in all_paths:
            write_order.append((path, self.files[path]))

        # Add (listfile) after user files so it references all of them
        listfile_path = "(listfile)"
        # Rebuild listfile to include itself
        all_internal_paths = all_paths + [listfile_path]
        listfile_content = "\r\n".join(all_internal_paths).encode('utf-8')
        write_order.append((listfile_path, listfile_content))

        num_files = len(write_order)
        hash_table_size = max(16, _next_power_of_2(num_files * 2))

        # -- Calculate file data offsets --
        data_offset = _MPQ_HEADER_SIZE  # file data starts right after header
        block_entries = []  # (file_offset, compressed_size, uncompressed_size, flags)
        file_data_blobs = []

        current_offset = data_offset
        for _path, data in write_order:
            size = len(data)
            block_entries.append((current_offset, size, size, _FILE_FLAGS))
            file_data_blobs.append(data)
            current_offset += size

        hash_table_offset = current_offset
        block_table_offset = hash_table_offset + hash_table_size * 16
        archive_size = block_table_offset + num_files * 16

        # -- Build hash table --
        # Each entry: (hash_a, hash_b, locale, platform, block_index)
        hash_table = [(_HASH_ENTRY_EMPTY, _HASH_ENTRY_EMPTY,
                        _HASH_LOCALE_NEUTRAL, _HASH_PLATFORM_DEFAULT,
                        _HASH_ENTRY_EMPTY)] * hash_table_size
        # Convert to mutable list
        hash_table = list(hash_table)

        for block_idx, (path, _data) in enumerate(write_order):
            hash_index = _hash_string(path, 0) % hash_table_size
            name_a = _hash_string(path, 1)
            name_b = _hash_string(path, 2)

            # Linear probe to find an empty slot
            for probe in range(hash_table_size):
                slot = (hash_index + probe) % hash_table_size
                if hash_table[slot][4] == _HASH_ENTRY_EMPTY:
                    hash_table[slot] = (name_a, name_b,
                                        _HASH_LOCALE_NEUTRAL,
                                        _HASH_PLATFORM_DEFAULT,
                                        block_idx)
                    break
            else:
                # Should never happen -- table is >= 2x file count
                raise RuntimeError(
                    "Hash table full; cannot insert '{}'".format(path)
                )

        # -- Write the archive --
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

        with open(output_path, 'wb') as f:
            # Header (32 bytes)
            f.write(_MPQ_MAGIC)                                  # magic
            f.write(struct.pack('<I', _MPQ_HEADER_SIZE))         # header size
            f.write(struct.pack('<I', archive_size))             # archive size
            f.write(struct.pack('<H', _MPQ_FORMAT_V1))           # format version
            f.write(struct.pack('<H', _SECTOR_SIZE_SHIFT))       # sector size shift
            f.write(struct.pack('<I', hash_table_offset))        # hash table offset
            f.write(struct.pack('<I', block_table_offset))       # block table offset
            f.write(struct.pack('<I', hash_table_size))          # hash table entries
            f.write(struct.pack('<I', num_files))                # block table entries

            # File data blocks
            for blob in file_data_blobs:
                f.write(blob)

            # Hash table
            for (ha, hb, locale, platform, block_idx) in hash_table:
                f.write(struct.pack('<I', ha))
                f.write(struct.pack('<I', hb))
                f.write(struct.pack('<H', locale))
                f.write(struct.pack('<H', platform))
                f.write(struct.pack('<I', block_idx))

            # Block table
            for (file_ofs, comp_size, uncomp_size, flags) in block_entries:
                f.write(struct.pack('<I', file_ofs))
                f.write(struct.pack('<I', comp_size))
                f.write(struct.pack('<I', uncomp_size))
                f.write(struct.pack('<I', flags))

        log.info("Wrote MPQ v1 archive: %s (%d files, %d bytes)",
                 output_path, num_files, archive_size)
        return output_path


# ---------------------------------------------------------------------------
# MPQ info reader (minimal, for the info subcommand)
# ---------------------------------------------------------------------------

def read_mpq_info(mpq_path):
    """
    Read and display basic MPQ header information.

    Args:
        mpq_path: Path to an MPQ archive.

    Returns:
        dict: Header fields.

    Raises:
        ValueError: If the file is not a valid MPQ archive.
    """
    with open(mpq_path, 'rb') as f:
        magic = f.read(4)
        if magic != _MPQ_MAGIC:
            raise ValueError(
                "Not an MPQ archive (magic: {!r})".format(magic)
            )

        header_size = struct.unpack('<I', f.read(4))[0]
        archive_size = struct.unpack('<I', f.read(4))[0]
        format_version = struct.unpack('<H', f.read(2))[0]
        sector_shift = struct.unpack('<H', f.read(2))[0]
        hash_table_offset = struct.unpack('<I', f.read(4))[0]
        block_table_offset = struct.unpack('<I', f.read(4))[0]
        hash_table_entries = struct.unpack('<I', f.read(4))[0]
        block_table_entries = struct.unpack('<I', f.read(4))[0]

        info = {
            'header_size': header_size,
            'archive_size': archive_size,
            'format_version': format_version,
            'sector_size_shift': sector_shift,
            'sector_size': 512 << sector_shift,
            'hash_table_offset': hash_table_offset,
            'block_table_offset': block_table_offset,
            'hash_table_entries': hash_table_entries,
            'block_table_entries': block_table_entries,
        }

        # Try to read (listfile) for file listing
        listfile_lines = _try_read_listfile(f, info)
        if listfile_lines is not None:
            info['listfile'] = listfile_lines

        return info


def _try_read_listfile(f, header_info):
    """
    Attempt to locate and read the (listfile) from an MPQ archive.

    Searches the hash table for '(listfile)' and reads its data from the
    block table entry. Only works for uncompressed single-unit files.

    Returns:
        list[str] or None: Lines from (listfile), or None if not found.
    """
    listfile_name = "(listfile)"
    hash_table_offset = header_info['hash_table_offset']
    block_table_offset = header_info['block_table_offset']
    hash_table_entries = header_info['hash_table_entries']

    # Compute hashes for (listfile)
    target_index = _hash_string(listfile_name, 0) % hash_table_entries
    target_a = _hash_string(listfile_name, 1)
    target_b = _hash_string(listfile_name, 2)

    # Search hash table
    block_idx = None
    for probe in range(hash_table_entries):
        slot = (target_index + probe) % hash_table_entries
        f.seek(hash_table_offset + slot * 16)
        ha = struct.unpack('<I', f.read(4))[0]
        hb = struct.unpack('<I', f.read(4))[0]
        _locale = struct.unpack('<H', f.read(2))[0]
        _platform = struct.unpack('<H', f.read(2))[0]
        bi = struct.unpack('<I', f.read(4))[0]

        if bi == _HASH_ENTRY_EMPTY:
            # Empty slot -- file not in archive
            break
        if ha == target_a and hb == target_b:
            block_idx = bi
            break

    if block_idx is None:
        return None

    # Read block table entry
    f.seek(block_table_offset + block_idx * 16)
    file_offset = struct.unpack('<I', f.read(4))[0]
    compressed_size = struct.unpack('<I', f.read(4))[0]
    _uncompressed_size = struct.unpack('<I', f.read(4))[0]
    flags = struct.unpack('<I', f.read(4))[0]

    if not (flags & _FILE_EXISTS):
        return None

    # Read file data (only handles uncompressed / single unit)
    f.seek(file_offset)
    data = f.read(compressed_size)

    try:
        text = data.decode('utf-8')
        return [line.strip() for line in text.splitlines() if line.strip()]
    except UnicodeDecodeError:
        return None


# ---------------------------------------------------------------------------
# PurePythonMPQReader
# ---------------------------------------------------------------------------

class PurePythonMPQReader:
    """
    Reads MPQ v1 archives in pure Python.

    Handles uncompressed single-unit files (as created by PurePythonMPQWriter).
    Does not support encrypted or compressed files (would need zlib/bzip2).
    """

    def __init__(self, mpq_path):
        """Open an MPQ archive for reading."""
        self.mpq_path = os.path.abspath(mpq_path)
        self._header = None
        self._hash_table = None
        self._block_table = None
        self._read_tables()

    def _read_tables(self):
        """Read and cache the header, hash table, and block table."""
        with open(self.mpq_path, 'rb') as f:
            # Read header
            magic = f.read(4)
            if magic != _MPQ_MAGIC:
                raise ValueError("Not an MPQ archive: {}".format(self.mpq_path))

            header_size = struct.unpack('<I', f.read(4))[0]
            archive_size = struct.unpack('<I', f.read(4))[0]
            format_version = struct.unpack('<H', f.read(2))[0]
            sector_shift = struct.unpack('<H', f.read(2))[0]
            hash_table_offset = struct.unpack('<I', f.read(4))[0]
            block_table_offset = struct.unpack('<I', f.read(4))[0]
            hash_table_entries = struct.unpack('<I', f.read(4))[0]
            block_table_entries = struct.unpack('<I', f.read(4))[0]

            self._header = {
                'header_size': header_size,
                'archive_size': archive_size,
                'format_version': format_version,
                'sector_size_shift': sector_shift,
                'hash_table_offset': hash_table_offset,
                'block_table_offset': block_table_offset,
                'hash_table_entries': hash_table_entries,
                'block_table_entries': block_table_entries,
            }

            # Read hash table
            f.seek(hash_table_offset)
            self._hash_table = []
            for _ in range(hash_table_entries):
                ha = struct.unpack('<I', f.read(4))[0]
                hb = struct.unpack('<I', f.read(4))[0]
                locale = struct.unpack('<H', f.read(2))[0]
                platform = struct.unpack('<H', f.read(2))[0]
                block_idx = struct.unpack('<I', f.read(4))[0]
                self._hash_table.append((ha, hb, locale, platform, block_idx))

            # Read block table
            f.seek(block_table_offset)
            self._block_table = []
            for _ in range(block_table_entries):
                file_ofs = struct.unpack('<I', f.read(4))[0]
                comp_size = struct.unpack('<I', f.read(4))[0]
                uncomp_size = struct.unpack('<I', f.read(4))[0]
                flags = struct.unpack('<I', f.read(4))[0]
                self._block_table.append((file_ofs, comp_size, uncomp_size, flags))

    def _find_file(self, filename):
        """Find a file's block table index by filename hash lookup."""
        hash_table_size = self._header['hash_table_entries']
        target_index = _hash_string(filename, 0) % hash_table_size
        target_a = _hash_string(filename, 1)
        target_b = _hash_string(filename, 2)

        for probe in range(hash_table_size):
            slot = (target_index + probe) % hash_table_size
            ha, hb, locale, platform, block_idx = self._hash_table[slot]

            if block_idx == _HASH_ENTRY_EMPTY:
                return None  # Empty slot, file not found
            if ha == target_a and hb == target_b:
                return block_idx

        return None

    def list_files(self):
        """List all files in the archive using (listfile).

        Returns:
            list[str]: Sorted list of file paths, or empty if no listfile.
        """
        block_idx = self._find_file("(listfile)")
        if block_idx is None:
            return []

        data = self._read_block(block_idx)
        if data is None:
            return []

        try:
            text = data.decode('utf-8')
            return sorted([line.strip() for line in text.splitlines()
                           if line.strip()])
        except UnicodeDecodeError:
            return []

    def _read_block(self, block_idx):
        """Read file data from a block table entry.

        Only supports uncompressed single-unit files.
        """
        if block_idx >= len(self._block_table):
            return None

        file_ofs, comp_size, uncomp_size, flags = self._block_table[block_idx]

        if not (flags & _FILE_EXISTS):
            return None

        with open(self.mpq_path, 'rb') as f:
            f.seek(file_ofs)
            data = f.read(comp_size)

        return data

    def read_file(self, filename):
        """Read a file from the archive.

        Args:
            filename: MPQ-internal path (backslash separators).

        Returns:
            bytes: File contents.

        Raises:
            KeyError: If file not found.
        """
        # Normalize to backslash
        filename = filename.replace('/', '\\')
        block_idx = self._find_file(filename)
        if block_idx is None:
            raise KeyError("File not found in archive: {}".format(filename))

        data = self._read_block(block_idx)
        if data is None:
            raise KeyError("Cannot read file: {}".format(filename))

        return data

    def extract_file(self, filename, output_path):
        """Extract a single file to disk.

        Args:
            filename: MPQ-internal path.
            output_path: Destination file path.

        Returns:
            str: Absolute path of extracted file.
        """
        data = self.read_file(filename)
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

        with open(output_path, 'wb') as f:
            f.write(data)

        return output_path

    def extract_all(self, output_dir):
        """Extract all files to a directory.

        Uses (listfile) to get filenames. Files are extracted preserving
        their internal MPQ path structure (with backslashes converted to
        OS path separators).

        Args:
            output_dir: Base output directory.

        Returns:
            list[str]: List of extracted file paths.
        """
        files = self.list_files()
        extracted = []

        for filename in files:
            # Convert MPQ path to OS path
            rel_path = filename.replace('\\', os.sep)
            output_path = os.path.join(output_dir, rel_path)

            try:
                self.extract_file(filename, output_path)
                extracted.append(output_path)
            except (KeyError, IOError) as e:
                print("  SKIP {} -- {}".format(filename, e))

        return extracted


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _collect_files_from_dir(content_dir):
    """
    Walk a directory tree and collect files with their MPQ-internal paths.

    The internal path is the relative path from content_dir with backslash
    separators, matching MPQ convention.

    Returns:
        list[(str, bytes)]: List of (internal_path, file_data) tuples.
    """
    content_dir = os.path.abspath(content_dir)
    collected = []

    for dirpath, _dirnames, filenames in os.walk(content_dir):
        for filename in sorted(filenames):
            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, content_dir)
            # Normalise to backslash for MPQ convention
            internal_path = rel_path.replace(os.sep, '\\')

            with open(filepath, 'rb') as fh:
                data = fh.read()
            collected.append((internal_path, data))

    return collected


def main():
    parser = argparse.ArgumentParser(
        description='Pure-Python MPQ v1 archive tool for WoW 3.3.5a')
    subparsers = parser.add_subparsers(dest='command')

    # -- create ---------------------------------------------------------
    p_create = subparsers.add_parser(
        'create', help='Create an MPQ v1 archive')
    p_create.add_argument(
        'output', help='Output .mpq file path')
    p_create.add_argument(
        '--dir',
        help='Pack all files from a directory (internal paths = relative paths)')
    p_create.add_argument(
        '--add', action='append', default=[],
        metavar='MPQ_PATH:LOCAL_FILE',
        help='Add a file with explicit internal path. '
             'Format: "World\\Maps\\Test\\Test.wdt:./test.wdt". '
             'Can be specified multiple times.')

    # -- info -----------------------------------------------------------
    p_info = subparsers.add_parser(
        'info', help='Show MPQ archive header information')
    p_info.add_argument(
        'archive', help='Input .mpq file path')

    # -- list -----------------------------------------------------------
    p_list = subparsers.add_parser(
        'list', help='List files in an MPQ archive')
    p_list.add_argument(
        'archive', help='Input .mpq file path')
    p_list.add_argument(
        '--pattern', help='Filter files by glob pattern (e.g. "*.adt")')

    # -- extract --------------------------------------------------------
    p_extract = subparsers.add_parser(
        'extract', help='Extract files from an MPQ archive')
    p_extract.add_argument(
        'archive', help='Input .mpq file path')
    p_extract.add_argument(
        '-o', '--output', default='.',
        help='Output directory (default: current directory)')
    p_extract.add_argument(
        '--file', action='append', default=[],
        help='Extract specific file(s). Can be specified multiple times. '
             'If not specified, extracts all files.')

    args = parser.parse_args()

    if args.command == 'create':
        writer = PurePythonMPQWriter()
        file_count = 0

        # Add files from --dir
        if args.dir:
            if not os.path.isdir(args.dir):
                print("Error: '{}' is not a directory".format(args.dir),
                      file=sys.stderr)
                sys.exit(1)
            for internal_path, data in _collect_files_from_dir(args.dir):
                writer.add_file(internal_path, data)
                file_count += 1
                print("  + {} ({} bytes)".format(internal_path, len(data)))

        # Add files from --add
        for spec in args.add:
            if ':' not in spec:
                print("Error: --add format must be 'MPQ_PATH:LOCAL_FILE', "
                      "got '{}'".format(spec), file=sys.stderr)
                sys.exit(1)
            mpq_path, local_file = spec.split(':', 1)
            if not os.path.isfile(local_file):
                print("Error: file not found: {}".format(local_file),
                      file=sys.stderr)
                sys.exit(1)
            with open(local_file, 'rb') as fh:
                data = fh.read()
            writer.add_file(mpq_path, data)
            file_count += 1
            print("  + {} ({} bytes)".format(mpq_path, len(data)))

        if file_count == 0:
            print("Error: no files to pack. Use --dir or --add.",
                  file=sys.stderr)
            sys.exit(1)

        result = writer.write(args.output)
        # +1 for the auto-generated (listfile)
        print("\nCreated {} ({} files + listfile)".format(result, file_count))

    elif args.command == 'info':
        if not os.path.isfile(args.archive):
            print("Error: file not found: {}".format(args.archive),
                  file=sys.stderr)
            sys.exit(1)

        try:
            info = read_mpq_info(args.archive)
        except ValueError as e:
            print("Error: {}".format(e), file=sys.stderr)
            sys.exit(1)

        print("MPQ Archive: {}".format(args.archive))
        print("  Format version : {}".format(info['format_version']))
        print("  Header size    : {} bytes".format(info['header_size']))
        print("  Archive size   : {} bytes".format(info['archive_size']))
        print("  Sector size    : {} bytes (shift={})".format(
            info['sector_size'], info['sector_size_shift']))
        print("  Hash table     : offset={}, entries={}".format(
            info['hash_table_offset'], info['hash_table_entries']))
        print("  Block table    : offset={}, entries={}".format(
            info['block_table_offset'], info['block_table_entries']))

        if 'listfile' in info:
            print("\n  Files ({} entries):".format(len(info['listfile'])))
            for name in info['listfile']:
                print("    {}".format(name))
        else:
            print("\n  (listfile) not found or not readable")

    elif args.command == 'list':
        if not os.path.isfile(args.archive):
            print("Error: file not found: {}".format(args.archive),
                  file=sys.stderr)
            sys.exit(1)

        try:
            reader = PurePythonMPQReader(args.archive)
        except ValueError as e:
            print("Error: {}".format(e), file=sys.stderr)
            sys.exit(1)

        files = reader.list_files()
        if args.pattern:
            import fnmatch
            files = [f for f in files
                     if fnmatch.fnmatch(f.replace('\\', '/'), args.pattern)]

        print("Files in {} ({} entries):".format(args.archive, len(files)))
        for name in files:
            # Show file size if possible
            block_idx = reader._find_file(name)
            if block_idx is not None and block_idx < len(reader._block_table):
                size = reader._block_table[block_idx][2]  # uncompressed size
                print("  {:>10d}  {}".format(size, name))
            else:
                print("  {:>10s}  {}".format("???", name))

    elif args.command == 'extract':
        if not os.path.isfile(args.archive):
            print("Error: file not found: {}".format(args.archive),
                  file=sys.stderr)
            sys.exit(1)

        try:
            reader = PurePythonMPQReader(args.archive)
        except ValueError as e:
            print("Error: {}".format(e), file=sys.stderr)
            sys.exit(1)

        output_dir = os.path.abspath(args.output)

        if args.file:
            # Extract specific files
            for filename in args.file:
                try:
                    path = reader.extract_file(
                        filename,
                        os.path.join(output_dir,
                                     filename.replace('\\', os.sep)))
                    print("  {} ({} bytes)".format(
                        filename, os.path.getsize(path)))
                except KeyError as e:
                    print("  NOT FOUND: {}".format(filename),
                          file=sys.stderr)
        else:
            # Extract all
            extracted = reader.extract_all(output_dir)
            print("\nExtracted {} files to {}".format(
                len(extracted), output_dir))

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
