"""I2C operations for EDID devices."""

import time
import glob
from pathlib import Path
from datetime import datetime
from typing import List, Tuple

try:
    from smbus2 import SMBus

    SMBUS_AVAILABLE = True
except ImportError:
    SMBUS_AVAILABLE = False


# Standard EDID I2C address
EDID_ADDRESS = 0x50

# Write timing
PAGE_SIZE = 16  # Typical EEPROM page size
PAGE_WRITE_DELAY = 0.01  # 10ms delay after page write


def check_smbus_available() -> None:
    """Check if smbus2 is available."""
    if not SMBUS_AVAILABLE:
        raise ImportError(
            "smbus2 is required for I2C operations. Install it with: pip install smbus2"
        )


def discover_buses(verbose: bool = False) -> List[Tuple[int, bool]]:
    """
    Discover available I2C buses and check for EDID presence.

    Scans /dev/i2c-* devices and probes for EDID at address 0x50.

    Args:
        verbose: Print detailed scanning information

    Returns:
        List of tuples (bus_number, has_edid)
    """
    check_smbus_available()

    buses = []
    i2c_devices = sorted(glob.glob("/dev/i2c-*"))

    if verbose:
        print(f"Scanning {len(i2c_devices)} I2C device(s)...")

    for device in i2c_devices:
        # Extract bus number from device path
        bus_num = int(device.split("-")[-1])

        has_edid = False
        try:
            with SMBus(bus_num) as bus:
                # Try to read first byte of EDID
                # This will fail if no device at address 0x50
                data = bus.read_byte_data(EDID_ADDRESS, 0x00)
                # Check if it looks like EDID header (first byte should be 0x00)
                has_edid = data == 0x00

                if verbose:
                    status = "EDID detected" if has_edid else "No EDID"
                    print(f"  Bus {bus_num}: {status}")
        except (OSError, IOError) as e:
            if verbose:
                print(f"  Bus {bus_num}: Not accessible ({e})")
            pass

        buses.append((bus_num, has_edid))

    return buses


def read_edid(bus_num: int, verbose: bool = False) -> bytes:
    """
    Read complete EDID from I2C device.

    Reads base block (128 bytes) and all extension blocks.

    Args:
        bus_num: I2C bus number (e.g., 0 for /dev/i2c-0)
        verbose: Print detailed operation information

    Returns:
        Complete EDID data (128 * (1 + extension_count) bytes)

    Raises:
        OSError: If device cannot be accessed
        ValueError: If EDID data is invalid
    """
    check_smbus_available()

    if verbose:
        print(f"Opening I2C bus {bus_num}...")

    try:
        with SMBus(bus_num) as bus:
            if verbose:
                print(f"Reading base block from address 0x{EDID_ADDRESS:02X}...")

            # Read base block (128 bytes)
            base_block = bytearray()
            for offset in range(0, 128, 32):
                chunk = bus.read_i2c_block_data(
                    EDID_ADDRESS, offset, min(32, 128 - offset)
                )
                base_block.extend(chunk)

            if len(base_block) != 128:
                raise ValueError(
                    f"Failed to read complete base block (got {len(base_block)} bytes)"
                )

            if verbose:
                print("Read base block: 128 bytes")

            # Check extension count
            extension_count = base_block[126]

            if extension_count == 0:
                if verbose:
                    print("No extension blocks")
                return bytes(base_block)

            if verbose:
                print(f"Reading {extension_count} extension block(s)...")

            # Read extension blocks
            full_edid = bytearray(base_block)
            for ext_num in range(extension_count):
                ext_block = bytearray()
                base_offset = (ext_num + 1) * 128

                # For extensions, we may need to read in smaller chunks
                # Some displays have issues with large reads from extension blocks
                for offset in range(0, 128, 32):
                    addr = (
                        base_offset + offset
                    ) % 256  # Wrap around for 8-bit addressing
                    chunk = bus.read_i2c_block_data(
                        EDID_ADDRESS, addr, min(32, 128 - offset)
                    )
                    ext_block.extend(chunk)

                if len(ext_block) != 128:
                    raise ValueError(f"Failed to read extension block {ext_num + 1}")

                full_edid.extend(ext_block)

                if verbose:
                    print(f"  Extension {ext_num + 1}: 128 bytes")

            if verbose:
                print(f"Total EDID size: {len(full_edid)} bytes")

            return bytes(full_edid)

    except OSError as e:
        if e.errno == 13:  # Permission denied
            raise OSError(
                f"Permission denied accessing /dev/i2c-{bus_num}. "
                "Try running with sudo or add your user to the 'i2c' group."
            ) from e
        elif e.errno == 2:  # No such file
            raise OSError(
                f"I2C bus {bus_num} not found. Check that /dev/i2c-{bus_num} exists."
            ) from e
        else:
            raise


def backup_edid(bus_num: int, verbose: bool = False) -> Path:
    """
    Create a backup of EDID from device.

    Saves to ~/.edid-backups/ with timestamp.

    Args:
        bus_num: I2C bus number
        verbose: Print backup information

    Returns:
        Path to backup file
    """
    # Create backup directory
    backup_dir = Path.home() / ".edid-backups"
    backup_dir.mkdir(exist_ok=True)

    # Read current EDID
    edid_data = read_edid(bus_num, verbose=False)

    # Create timestamped filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"edid_bus{bus_num}_{timestamp}.bin"

    # Write backup
    backup_path.write_bytes(edid_data)

    if verbose:
        print(f"Backup saved: {backup_path}")
        print(f"Backup size: {len(edid_data)} bytes")

    return backup_path


def write_edid(bus_num: int, edid_data: bytes, verbose: bool = False) -> None:
    """
    Write EDID data to I2C device.

    Uses page-aligned writes with appropriate delays.
    Automatically creates backup before writing.

    Args:
        bus_num: I2C bus number
        edid_data: Complete EDID data to write
        verbose: Print detailed operation information

    Raises:
        ValueError: If EDID data is invalid
        OSError: If device cannot be accessed or write fails
    """
    check_smbus_available()

    # Validate data size
    if len(edid_data) % 128 != 0:
        raise ValueError(
            f"EDID data size must be multiple of 128 bytes (got {len(edid_data)})"
        )

    if verbose:
        print(f"Writing {len(edid_data)} bytes to I2C bus {bus_num}...")

    # Create backup first
    if verbose:
        print("Creating backup before write...")
    backup_path = backup_edid(bus_num, verbose=verbose)

    try:
        with SMBus(bus_num) as bus:
            # Write in page-sized chunks
            total_pages = (len(edid_data) + PAGE_SIZE - 1) // PAGE_SIZE

            for page_num in range(total_pages):
                offset = page_num * PAGE_SIZE
                end_offset = min(offset + PAGE_SIZE, len(edid_data))
                chunk = edid_data[offset:end_offset]

                if verbose:
                    print(
                        f"  Writing page {page_num + 1}/{total_pages} "
                        f"(offset 0x{offset:02X}, {len(chunk)} bytes)..."
                    )

                # Write the chunk
                bus.write_i2c_block_data(EDID_ADDRESS, offset % 256, list(chunk))

                # Wait for page write to complete
                time.sleep(PAGE_WRITE_DELAY)

            if verbose:
                print("Write complete, verifying...")

            # Verify write by reading back
            read_back = read_edid(bus_num, verbose=False)

            if read_back != edid_data:
                raise IOError(
                    "Write verification failed! Data read back does not match. "
                    f"Backup saved at: {backup_path}"
                )

            if verbose:
                print("Write verified successfully!")

    except Exception as e:
        print(f"\nWRITE FAILED: {e}")
        print(f"Backup available at: {backup_path}")
        raise


def test_writable(bus_num: int, verbose: bool = False) -> Tuple[bool, str]:
    """
    Test if EDID device is writable.

    Attempts to find a safe byte, write a test value, verify, and restore.
    Creates backup before testing.

    WARNING: This test modifies EDID data temporarily. While it attempts to
    use safe bytes and restore original values, there is inherent risk.

    Args:
        bus_num: I2C bus number
        verbose: Print detailed test information

    Returns:
        Tuple of (is_writable, message)
    """
    check_smbus_available()

    if verbose:
        print("=" * 70)
        print("EDID WRITE TEST")
        print("=" * 70)
        print("\nWARNING: This test temporarily modifies EDID data.")
        print(
            "A backup will be created first, and the original value will be restored."
        )
        print("However, there is inherent risk in writing to EDID.")
        print()

    try:
        # Create backup first
        if verbose:
            print("Creating backup before test...")
        backup_path = backup_edid(bus_num, verbose=verbose)

        # Read current EDID
        edid_data = read_edid(bus_num, verbose=False)

        # Import validator to find safe byte
        from .validator import find_safe_test_byte

        # Find safe byte to test
        test_offset = find_safe_test_byte(edid_data)

        if test_offset is None:
            return False, (
                "No safe test byte found in EDID. Cannot safely test write capability. "
                "Consider using a known good EDID file and write operation instead."
            )

        original_value = edid_data[test_offset]
        test_value = original_value ^ 0xFF  # Flip all bits

        if verbose:
            print(f"\nTest byte offset: 0x{test_offset:02X}")
            print(f"Original value: 0x{original_value:02X}")
            print(f"Test value: 0x{test_value:02X}")
            print("\nAttempting write...")

        with SMBus(bus_num) as bus:
            # Write test value
            bus.write_byte_data(EDID_ADDRESS, test_offset, test_value)
            time.sleep(PAGE_WRITE_DELAY)

            # Read back
            read_value = bus.read_byte_data(EDID_ADDRESS, test_offset)

            if verbose:
                print(f"Read back value: 0x{read_value:02X}")

            # Check if write succeeded
            write_successful = read_value == test_value

            # Restore original value
            if verbose:
                print("Restoring original value...")
            bus.write_byte_data(EDID_ADDRESS, test_offset, original_value)
            time.sleep(PAGE_WRITE_DELAY)

            # Verify restoration
            restored_value = bus.read_byte_data(EDID_ADDRESS, test_offset)

            if restored_value != original_value:
                return False, (
                    f"CRITICAL: Failed to restore original value! "
                    f"Expected 0x{original_value:02X}, got 0x{restored_value:02X}. "
                    f"Backup saved at: {backup_path}"
                )

            if verbose:
                print("Original value restored successfully")

            if write_successful:
                return True, "Device is writable (test passed)"
            else:
                return False, "Device is not writable (write-protected or read-only)"

    except OSError as e:
        if e.errno == 13:
            return False, (
                "Permission denied. Run with sudo or add user to 'i2c' group."
            )
        else:
            return False, f"I/O error during test: {e}"
    except Exception as e:
        return False, f"Test failed: {e}"


def validate_device_matches_file(
    bus_num: int, file_data: bytes, verbose: bool = False
) -> Tuple[bool, str]:
    """
    Validate that EDID device matches a binary file.

    Args:
        bus_num: I2C bus number
        file_data: EDID data from file
        verbose: Print comparison details

    Returns:
        Tuple of (matches, message)
    """
    if verbose:
        print(f"Reading EDID from bus {bus_num}...")

    try:
        device_data = read_edid(bus_num, verbose=False)
    except Exception as e:
        return False, f"Failed to read device: {e}"

    if len(device_data) != len(file_data):
        return False, (
            f"Size mismatch: device has {len(device_data)} bytes, "
            f"file has {len(file_data)} bytes"
        )

    if device_data == file_data:
        return True, "Device EDID matches file exactly"

    # Find differences
    diffs = []
    for i in range(len(device_data)):
        if device_data[i] != file_data[i]:
            diffs.append((i, device_data[i], file_data[i]))

    if verbose and diffs:
        print(f"\nFound {len(diffs)} byte difference(s):")
        for offset, dev_byte, file_byte in diffs[:10]:  # Show first 10
            print(
                f"  Offset 0x{offset:02X}: "
                f"device=0x{dev_byte:02X}, file=0x{file_byte:02X}"
            )
        if len(diffs) > 10:
            print(f"  ... and {len(diffs) - 10} more")

    return False, f"Mismatch: {len(diffs)} byte(s) differ"
