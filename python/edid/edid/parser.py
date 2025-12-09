"""EDID parsing and decoding functions."""

import struct
from typing import Dict, Any, List


def decode_hex(edid_data: bytes, verbose: bool = False) -> str:
    """
    Decode EDID as hexadecimal dump.

    Args:
        edid_data: EDID data
        verbose: Include additional formatting

    Returns:
        Formatted hex dump string
    """
    lines = []
    lines.append("=" * 70)
    lines.append("EDID HEX DUMP")
    lines.append("=" * 70)

    for block_num in range(len(edid_data) // 128):
        offset = block_num * 128
        block = edid_data[offset : offset + 128]

        if block_num == 0:
            lines.append("\nBase Block (128 bytes):")
        else:
            lines.append(f"\nExtension Block {block_num} (128 bytes):")

        lines.append("-" * 70)

        for i in range(0, 128, 16):
            hex_part = " ".join(f"{b:02X}" for b in block[i : i + 16])
            ascii_part = "".join(
                chr(b) if 32 <= b < 127 else "." for b in block[i : i + 16]
            )
            lines.append(f"{offset + i:04X}: {hex_part:<48}  {ascii_part}")

    lines.append("=" * 70)
    return "\n".join(lines)


def decode_manufacturer_id(data: bytes) -> str:
    """
    Decode 3-letter manufacturer ID from bytes 8-9.

    Manufacturer ID is compressed into 2 bytes using 5-bit ASCII (A-Z).

    Args:
        data: EDID data (at least 10 bytes)

    Returns:
        3-letter manufacturer code
    """
    if len(data) < 10:
        return "???"

    id_bytes = struct.unpack(">H", data[8:10])[0]

    # Extract 5-bit characters (bits 14-10, 9-5, 4-0)
    char1 = chr(((id_bytes >> 10) & 0x1F) + 64)
    char2 = chr(((id_bytes >> 5) & 0x1F) + 64)
    char3 = chr((id_bytes & 0x1F) + 64)

    return f"{char1}{char2}{char3}"


def decode_product_info(data: bytes) -> Dict[str, Any]:
    """
    Decode product information from EDID.

    Args:
        data: EDID data (at least 18 bytes)

    Returns:
        Dictionary with manufacturer, product code, serial number, week, year
    """
    if len(data) < 18:
        return {}

    manufacturer = decode_manufacturer_id(data)
    product_code = struct.unpack("<H", data[10:12])[0]
    serial_number = struct.unpack("<I", data[12:16])[0]
    week = data[16]
    year = 1990 + data[17]

    return {
        "manufacturer": manufacturer,
        "product_code": product_code,
        "serial_number": serial_number,
        "manufacture_week": week if week != 0 else None,
        "manufacture_year": year,
    }


def decode_version(data: bytes) -> str:
    """
    Decode EDID version from bytes 18-19.

    Args:
        data: EDID data (at least 20 bytes)

    Returns:
        Version string (e.g., "1.4")
    """
    if len(data) < 20:
        return "?.?"

    return f"{data[18]}.{data[19]}"


def decode_display_params(data: bytes) -> Dict[str, Any]:
    """
    Decode basic display parameters.

    Args:
        data: EDID data (at least 25 bytes)

    Returns:
        Dictionary with display parameters
    """
    if len(data) < 25:
        return {}

    video_input = data[20]
    is_digital = bool(video_input & 0x80)

    max_h_size = data[21]  # cm
    max_v_size = data[22]  # cm
    gamma_byte = data[23]
    gamma = (gamma_byte + 100) / 100 if gamma_byte != 0xFF else None

    features = data[24]

    return {
        "digital": is_digital,
        "max_h_size_cm": max_h_size if max_h_size != 0 else None,
        "max_v_size_cm": max_v_size if max_v_size != 0 else None,
        "gamma": gamma,
        "dpms_standby": bool(features & 0x80),
        "dpms_suspend": bool(features & 0x40),
        "dpms_active_off": bool(features & 0x20),
    }


def decode_detailed_timing(descriptor: bytes) -> Dict[str, Any]:
    """
    Decode detailed timing descriptor (18 bytes).

    Args:
        descriptor: 18-byte timing descriptor

    Returns:
        Dictionary with timing information
    """
    if len(descriptor) != 18:
        return {}

    # Check if this is a dummy descriptor
    if descriptor[0] == 0 and descriptor[1] == 0:
        return {"type": "dummy"}

    # Parse detailed timing
    pixel_clock = struct.unpack("<H", descriptor[0:2])[0] * 10000  # in Hz

    h_active = descriptor[2] | ((descriptor[4] & 0xF0) << 4)
    h_blank = descriptor[3] | ((descriptor[4] & 0x0F) << 8)
    v_active = descriptor[5] | ((descriptor[7] & 0xF0) << 4)
    v_blank = descriptor[6] | ((descriptor[7] & 0x0F) << 8)

    return {
        "type": "timing",
        "pixel_clock_hz": pixel_clock,
        "h_active": h_active,
        "h_blank": h_blank,
        "v_active": v_active,
        "v_blank": v_blank,
        "h_total": h_active + h_blank,
        "v_total": v_active + v_blank,
    }


def decode_descriptor_name(descriptor: bytes) -> str:
    """
    Decode display name from descriptor (type 0xFC).

    Args:
        descriptor: 18-byte descriptor

    Returns:
        Display name string
    """
    if len(descriptor) != 18 or descriptor[0] != 0 or descriptor[1] != 0:
        return ""

    if descriptor[3] == 0xFC:  # Display name
        name_bytes = descriptor[5:18]
        # Remove padding (0x0A and trailing spaces)
        name = name_bytes.split(b"\x0a")[0].decode("ascii", errors="ignore").strip()
        return name

    return ""


def decode_basic(edid_data: bytes, verbose: bool = False) -> str:
    """
    Decode EDID with basic information.

    Extracts: manufacturer, model, serial, resolution, refresh rate.

    Args:
        edid_data: EDID data
        verbose: Include additional details

    Returns:
        Formatted basic information string
    """
    lines = []
    lines.append("=" * 70)
    lines.append("EDID BASIC INFORMATION")
    lines.append("=" * 70)

    # Product information
    product = decode_product_info(edid_data)
    if product:
        lines.append(f"\nManufacturer: {product['manufacturer']}")
        lines.append(f"Product Code: 0x{product['product_code']:04X}")
        if product["serial_number"]:
            lines.append(f"Serial Number: {product['serial_number']}")
        if product["manufacture_week"]:
            lines.append(
                f"Manufactured: Week {product['manufacture_week']}, {product['manufacture_year']}"
            )
        else:
            lines.append(f"Manufactured: {product['manufacture_year']}")

    # EDID version
    version = decode_version(edid_data)
    lines.append(f"EDID Version: {version}")

    # Display parameters
    display = decode_display_params(edid_data)
    if display:
        lines.append(f"\nDisplay Type: {'Digital' if display['digital'] else 'Analog'}")
        if display["max_h_size_cm"] and display["max_v_size_cm"]:
            lines.append(
                f"Screen Size: {display['max_h_size_cm']} x {display['max_v_size_cm']} cm"
            )
            # Calculate diagonal in inches
            diagonal_cm = (
                display["max_h_size_cm"] ** 2 + display["max_v_size_cm"] ** 2
            ) ** 0.5
            diagonal_in = diagonal_cm / 2.54
            lines.append(f"Diagonal: {diagonal_in:.1f} inches")
        if display["gamma"]:
            lines.append(f"Gamma: {display['gamma']:.2f}")

    # Find display name in descriptors
    display_name = None
    for desc_offset in [54, 72, 90, 108]:
        if desc_offset + 18 <= len(edid_data):
            name = decode_descriptor_name(edid_data[desc_offset : desc_offset + 18])
            if name:
                display_name = name
                break

    if display_name:
        lines.append(f"\nDisplay Name: {display_name}")

    # Detailed timing descriptors
    lines.append("\nPreferred Timing (Detailed Descriptor):")
    timings = []
    for desc_offset in [54, 72, 90, 108]:
        if desc_offset + 18 <= len(edid_data):
            timing = decode_detailed_timing(edid_data[desc_offset : desc_offset + 18])
            if timing.get("type") == "timing":
                timings.append(timing)

    if timings:
        # First timing is preferred
        t = timings[0]
        refresh = t["pixel_clock_hz"] / (t["h_total"] * t["v_total"])
        lines.append(f"  Resolution: {t['h_active']} x {t['v_active']}")
        lines.append(f"  Refresh Rate: {refresh:.2f} Hz")
        lines.append(f"  Pixel Clock: {t['pixel_clock_hz'] / 1_000_000:.2f} MHz")

        if verbose and len(timings) > 1:
            lines.append(f"\nAdditional Timings: {len(timings) - 1}")

    # Extension blocks
    extension_count = edid_data[126] if len(edid_data) >= 127 else 0
    lines.append(f"\nExtension Blocks: {extension_count}")

    lines.append("=" * 70)
    return "\n".join(lines)


def decode_cea861_block(extension_data: bytes) -> Dict[str, Any]:
    """
    Decode CEA-861 extension block.

    Args:
        extension_data: 128-byte CEA-861 extension

    Returns:
        Dictionary with CEA-861 information
    """
    if len(extension_data) != 128 or extension_data[0] != 0x02:
        return {}

    revision = extension_data[1]
    dtd_offset = extension_data[2]

    # Parse flags
    flags = extension_data[3]
    underscan = bool(flags & 0x80)
    basic_audio = bool(flags & 0x40)
    ycbcr444 = bool(flags & 0x20)
    ycbcr422 = bool(flags & 0x10)

    info = {
        "revision": revision,
        "underscan_support": underscan,
        "basic_audio_support": basic_audio,
        "ycbcr444_support": ycbcr444,
        "ycbcr422_support": ycbcr422,
        "data_blocks": [],
    }

    # Parse data blocks (from byte 4 to dtd_offset)
    offset = 4
    while offset < dtd_offset and offset < 127:
        tag_byte = extension_data[offset]
        tag = (tag_byte >> 5) & 0x07
        length = tag_byte & 0x1F

        if offset + length + 1 > dtd_offset:
            break

        block_data = extension_data[offset + 1 : offset + 1 + length]

        block_info = {"tag": tag, "length": length}

        if tag == 1:  # Audio data block
            block_info["type"] = "Audio"
        elif tag == 2:  # Video data block
            block_info["type"] = "Video"
        elif tag == 3:  # Vendor specific
            block_info["type"] = "Vendor Specific"
        elif tag == 4:  # Speaker allocation
            block_info["type"] = "Speaker Allocation"
        else:
            block_info["type"] = f"Unknown (0x{tag:02X})"

        info["data_blocks"].append(block_info)
        offset += length + 1

    return info


def decode_deep(edid_data: bytes, verbose: bool = False) -> str:
    """
    Decode EDID with detailed information.

    Includes all timings, extensions, and detailed parsing.

    Args:
        edid_data: EDID data
        verbose: Include verbose output

    Returns:
        Formatted detailed information string
    """
    lines = []
    lines.append("=" * 70)
    lines.append("EDID DETAILED INFORMATION")
    lines.append("=" * 70)

    # Start with basic info
    basic_output = decode_basic(edid_data, verbose=False)
    # Remove header/footer from basic output
    basic_lines = basic_output.split("\n")[3:-1]
    lines.extend(basic_lines)

    # Detailed timing descriptors
    lines.append("\n" + "-" * 70)
    lines.append("DETAILED TIMING DESCRIPTORS")
    lines.append("-" * 70)

    for i, desc_offset in enumerate([54, 72, 90, 108], 1):
        if desc_offset + 18 <= len(edid_data):
            descriptor = edid_data[desc_offset : desc_offset + 18]

            # Check for display name
            name = decode_descriptor_name(descriptor)
            if name:
                lines.append(f"\nDescriptor {i}: Display Name")
                lines.append(f"  Name: {name}")
                continue

            # Parse timing
            timing = decode_detailed_timing(descriptor)
            if timing.get("type") == "timing":
                t = timing
                refresh = t["pixel_clock_hz"] / (t["h_total"] * t["v_total"])
                lines.append(f"\nDescriptor {i}: Detailed Timing")
                lines.append(f"  Resolution: {t['h_active']} x {t['v_active']}")
                lines.append(f"  Refresh Rate: {refresh:.2f} Hz")
                lines.append(
                    f"  Pixel Clock: {t['pixel_clock_hz'] / 1_000_000:.2f} MHz"
                )
                lines.append(
                    f"  Horizontal: {t['h_active']} active, {t['h_blank']} blank, {t['h_total']} total"
                )
                lines.append(
                    f"  Vertical: {t['v_active']} active, {t['v_blank']} blank, {t['v_total']} total"
                )
            elif timing.get("type") == "dummy":
                lines.append(f"\nDescriptor {i}: Dummy/Unused")

    # Extension blocks
    extension_count = edid_data[126] if len(edid_data) >= 127 else 0
    if extension_count > 0:
        lines.append("\n" + "-" * 70)
        lines.append("EXTENSION BLOCKS")
        lines.append("-" * 70)

        for i in range(extension_count):
            offset = 128 * (i + 1)
            if offset + 128 <= len(edid_data):
                extension = edid_data[offset : offset + 128]
                tag = extension[0]

                lines.append(f"\nExtension {i + 1}:")

                if tag == 0x02:  # CEA-861
                    lines.append("  Type: CEA-861 (HDMI/Consumer Electronics)")
                    cea_info = decode_cea861_block(extension)
                    if cea_info:
                        lines.append(f"  Revision: {cea_info['revision']}")
                        lines.append(f"  Underscan: {cea_info['underscan_support']}")
                        lines.append(
                            f"  Basic Audio: {cea_info['basic_audio_support']}"
                        )
                        lines.append(f"  YCbCr 4:4:4: {cea_info['ycbcr444_support']}")
                        lines.append(f"  YCbCr 4:2:2: {cea_info['ycbcr422_support']}")

                        if cea_info["data_blocks"]:
                            lines.append(
                                f"  Data Blocks: {len(cea_info['data_blocks'])}"
                            )
                            for block in cea_info["data_blocks"]:
                                lines.append(
                                    f"    - {block['type']} ({block['length']} bytes)"
                                )
                elif tag == 0x70:  # DisplayID
                    lines.append("  Type: DisplayID")
                elif tag == 0xF0:  # Block Map
                    lines.append("  Type: Block Map")
                else:
                    lines.append(f"  Type: Unknown (0x{tag:02X})")

    lines.append("=" * 70)
    return "\n".join(lines)
