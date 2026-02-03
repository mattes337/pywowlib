"""
VMap/MMap server data generator for WoW WotLK 3.3.5a.

Provides optional integration with TrinityCore/CMaNGOS server tools
(vmap4extractor, vmap4assembler, mmaps_generator) for generating
server-side collision and pathfinding data.

These tools are not bundled with pywowlib. If the tools are not found,
all functions log a warning and return None gracefully without failing
the build pipeline.
"""

import os
import subprocess
import logging
import shutil

log = logging.getLogger(__name__)


# Tool executable names (without extension; .exe added on Windows)
_VMAP_EXTRACTOR = 'vmap4extractor'
_VMAP_ASSEMBLER = 'vmap4assembler'
_MMAP_GENERATOR = 'mmaps_generator'


def find_tool(tool_name, search_dirs=None):
    """
    Locate a server tool executable.

    Searches in order:
    1. search_dirs (if provided)
    2. System PATH (via shutil.which)
    3. Common install locations

    Args:
        tool_name: Base name of the tool (e.g. 'vmap4extractor').
        search_dirs: Optional list of directories to search first.

    Returns:
        str: Absolute path to the tool, or None if not found.
    """
    # Check search_dirs first
    if search_dirs:
        if isinstance(search_dirs, str):
            search_dirs = [search_dirs]
        for d in search_dirs:
            for ext in ('', '.exe'):
                candidate = os.path.join(d, tool_name + ext)
                if os.path.isfile(candidate):
                    return os.path.abspath(candidate)

    # Check system PATH
    found = shutil.which(tool_name)
    if found:
        return os.path.abspath(found)

    # Check common locations
    common_dirs = [
        os.path.join(os.path.expanduser('~'), 'TrinityCore', 'bin'),
        os.path.join(os.path.expanduser('~'), 'trinitycore', 'bin'),
        '/usr/local/bin',
        '/opt/trinitycore/bin',
    ]
    for d in common_dirs:
        for ext in ('', '.exe'):
            candidate = os.path.join(d, tool_name + ext)
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)

    return None


def generate_vmaps(wow_data_dir, output_dir, map_name=None, tools_dir=None):
    """
    Run vmap4extractor + vmap4assembler to generate server collision data.

    Args:
        wow_data_dir: Path to WoW Data/ directory (containing MPQ files).
        output_dir: Where to write vmaps/ output.
        map_name: Optional specific map to extract (None=all maps).
        tools_dir: Optional path to directory containing vmap tools.

    Returns:
        str: Path to vmaps/ directory, or None if tools unavailable.

    Raises:
        FileNotFoundError: If wow_data_dir doesn't exist.
        RuntimeError: If extraction fails (non-zero exit code).
    """
    if not os.path.isdir(wow_data_dir):
        raise FileNotFoundError(
            "WoW Data directory not found: {}".format(wow_data_dir))

    extractor = find_tool(_VMAP_EXTRACTOR, tools_dir)
    assembler = find_tool(_VMAP_ASSEMBLER, tools_dir)

    if not extractor:
        log.warning("vmap4extractor not found; skipping vmap generation. "
                    "Install TrinityCore tools to enable server collision data.")
        return None

    if not assembler:
        log.warning("vmap4assembler not found; skipping vmap assembly. "
                    "Install TrinityCore tools to enable server collision data.")
        return None

    os.makedirs(output_dir, exist_ok=True)
    vmaps_dir = os.path.join(output_dir, 'vmaps')
    buildings_dir = os.path.join(output_dir, 'Buildings')

    # Step 1: Extract
    log.info("Running vmap4extractor...")
    cmd = [extractor]
    if map_name:
        cmd.extend(['-d', wow_data_dir, '-m', map_name])
    else:
        cmd.extend(['-d', wow_data_dir])

    result = subprocess.run(cmd, cwd=output_dir,
                           capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "vmap4extractor failed (exit code {}):\n{}".format(
                result.returncode, result.stderr or result.stdout))

    # Step 2: Assemble
    log.info("Running vmap4assembler...")
    os.makedirs(vmaps_dir, exist_ok=True)

    cmd = [assembler, buildings_dir, vmaps_dir]
    result = subprocess.run(cmd, cwd=output_dir,
                           capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "vmap4assembler failed (exit code {}):\n{}".format(
                result.returncode, result.stderr or result.stdout))

    log.info("VMap generation complete: %s", vmaps_dir)
    return vmaps_dir


def generate_mmaps(vmaps_dir, output_dir, map_id=None, tools_dir=None):
    """
    Run mmaps_generator to generate server pathfinding meshes.
    Requires vmaps to be generated first.

    Args:
        vmaps_dir: Path to vmaps/ from generate_vmaps().
        output_dir: Where to write mmaps/ output.
        map_id: Optional specific map ID (None=all maps).
        tools_dir: Optional path to directory containing mmap tools.

    Returns:
        str: Path to mmaps/ directory, or None if tools unavailable.

    Raises:
        FileNotFoundError: If vmaps_dir doesn't exist.
        RuntimeError: If generation fails (non-zero exit code).
    """
    if not os.path.isdir(vmaps_dir):
        raise FileNotFoundError(
            "vmaps directory not found: {}. Run generate_vmaps() first.".format(
                vmaps_dir))

    generator = find_tool(_MMAP_GENERATOR, tools_dir)
    if not generator:
        log.warning("mmaps_generator not found; skipping mmap generation. "
                    "Install TrinityCore tools to enable server pathfinding.")
        return None

    mmaps_dir = os.path.join(output_dir, 'mmaps')
    os.makedirs(mmaps_dir, exist_ok=True)

    log.info("Running mmaps_generator...")
    cmd = [generator, '--offMeshInput', vmaps_dir]
    if map_id is not None:
        cmd.extend(['--mapId', str(map_id)])

    result = subprocess.run(cmd, cwd=output_dir,
                           capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "mmaps_generator failed (exit code {}):\n{}".format(
                result.returncode, result.stderr or result.stdout))

    log.info("MMap generation complete: %s", mmaps_dir)
    return mmaps_dir


def generate_server_data(wow_data_dir, output_dir, map_name=None,
                         map_id=None, tools_dir=None):
    """
    Convenience: run both vmap and mmap generation in sequence.
    Skips gracefully if tools are not found (logs warning).

    Args:
        wow_data_dir: Path to WoW Data/ directory (containing MPQ files).
        output_dir: Where to write vmaps/ and mmaps/ output.
        map_name: Optional specific map name for vmap extraction.
        map_id: Optional specific map ID for mmap generation.
        tools_dir: Optional path to directory containing server tools.

    Returns:
        dict: {
            'vmaps_dir': str or None,
            'mmaps_dir': str or None,
        }
    """
    vmaps_dir = generate_vmaps(
        wow_data_dir=wow_data_dir,
        output_dir=output_dir,
        map_name=map_name,
        tools_dir=tools_dir,
    )

    mmaps_dir = None
    if vmaps_dir:
        mmaps_dir = generate_mmaps(
            vmaps_dir=vmaps_dir,
            output_dir=output_dir,
            map_id=map_id,
            tools_dir=tools_dir,
        )

    return {
        'vmaps_dir': vmaps_dir,
        'mmaps_dir': mmaps_dir,
    }
