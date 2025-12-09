"""EDID validation functions."""

from typing import Optional, Tuple


# EDID header magic bytes
EDID_HEADER = bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])


def validate_checksum(edid_block: bytes) -> bool:
    """
    Verify EDID block checksum.

    The sum of all 128 bytes must equal 0 (mod 256).

    Args:
        edid_block: 128-byte EDID block

    Returns:
        True if checksum is valid
    """
    if len(edid_block) != 128:
        return False
    return sum(edid_block) % 256 == 0


def calculate_checksum(edid_block: bytearray) -> int:
    """
    Calculate correct checksum for EDID block.

    Args:
        edid_block: 128-byte EDID block (will be modified)

    Returns:
        Calculated checksum value
    """
    if len(edid_block) != 128:
        raise ValueError("EDID block must be exactly 128 bytes")

    edid_block[127] = 0  # Zero out checksum byte
    checksum = (256 - (sum(edid_block[:127]) % 256)) % 256
    return checksum


def validate_header(edid_data: bytes) -> bool:
    """
    Verify EDID header magic bytes.

    First 8 bytes must be: 00 FF FF FF FF FF FF 00

    Args:
        edid_data: EDID data (at least 8 bytes)

    Returns:
        True if header is valid
    """
    if len(edid_data) < 8:
        return False
    return edid_data[:8] == EDID_HEADER


def validate_structure(edid_data: bytes) -> Tuple[bool, str]:
    """
    Validate overall EDID structure.

    Checks:
    - Minimum size (128 bytes)
    - Valid header
    - Base block checksum
    - Extension block checksums (if present)

    Args:
        edid_data: Complete EDID data

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(edid_data) < 128:
        return False, "EDID data too short (minimum 128 bytes)"

    if len(edid_data) % 128 != 0:
        return (
            False,
            f"EDID data size must be multiple of 128 bytes (got {len(edid_data)})",
        )

    # Validate header
    if not validate_header(edid_data):
        return False, "Invalid EDID header (expected 00 FF FF FF FF FF FF 00)"

    # Validate base block checksum
    base_block = edid_data[:128]
    if not validate_checksum(base_block):
        return False, "Invalid base block checksum"

    # Check extension count matches actual data
    extension_count = edid_data[126]
    expected_size = 128 * (1 + extension_count)
    if len(edid_data) != expected_size:
        return (
            False,
            f"Extension count mismatch: byte 126 indicates {extension_count} extensions "
            f"(expected {expected_size} bytes, got {len(edid_data)})",
        )

    # Validate extension block checksums
    for i in range(extension_count):
        offset = 128 * (i + 1)
        ext_block = edid_data[offset : offset + 128]
        if not validate_checksum(ext_block):
            return False, f"Invalid checksum in extension block {i + 1}"

    return True, "Valid EDID structure"


def find_safe_test_byte(edid_data: bytes) -> Optional[int]:
    """
    Find a safe byte to use for write testing.

    Looks for:
    1. Unused detailed timing descriptor padding (dummy descriptor)
    2. Unused standard timing slots (value 0x01 0x01)

    Args:
        edid_data: EDID data (at least 128 bytes)

    Returns:
        Byte offset of a safe test byte, or None if no safe byte found
    """
    if len(edid_data) < 128:
        return None

    # Check for dummy descriptors in detailed timing descriptor area (bytes 54-125)
    # A dummy descriptor starts with 0x00 0x00 and has padding that can be safely modified
    for desc_offset in [54, 72, 90, 108]:
        if desc_offset + 18 <= len(edid_data):
            # Check if this is a dummy descriptor (first two bytes are 0x00)
            if edid_data[desc_offset] == 0x00 and edid_data[desc_offset + 1] == 0x00:
                # Use byte at offset +5 (flag byte, often 0x00 in dummy descriptors)
                test_offset = desc_offset + 5
                if test_offset < 127:  # Don't use checksum byte
                    return test_offset

    # Check for unused standard timing slots (bytes 38-53)
    # Unused slots have value 0x01 0x01
    for st_offset in range(38, 54, 2):
        if st_offset + 1 < len(edid_data):
            if edid_data[st_offset] == 0x01 and edid_data[st_offset + 1] == 0x01:
                return st_offset

    # No safe byte found
    return None


def recalculate_checksums(edid_data: bytearray) -> None:
    """
    Recalculate and update checksums for all EDID blocks.

    Args:
        edid_data: EDID data (will be modified in-place)
    """
    if len(edid_data) % 128 != 0:
        raise ValueError("EDID data size must be multiple of 128 bytes")

    num_blocks = len(edid_data) // 128
    for i in range(num_blocks):
        offset = i * 128
        block = edid_data[offset : offset + 128]
        checksum = calculate_checksum(block)
        edid_data[offset + 127] = checksum
