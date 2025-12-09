# EDID Manager

A command-line tool for managing EDID (Extended Display Identification Data) via I2C devices on Linux.

## Features

- 🔍 **Discover** I2C buses and detect EDID-enabled displays
- 📖 **Read** complete EDID data including all extension blocks
- 🔎 **Decode** EDID into human-readable format (hex, basic, or detailed)
- ✍️ **Write** EDID data to devices with automatic backup and verification
- ✅ **Validate** that device EDID matches a reference file
- 🧪 **Test** device write capability safely with automatic backup/restore

## Installation

### Prerequisites

- Python 3.9 or higher
- [uv](https://github.com/astral-sh/uv) package manager
- I2C bus access (user must be in `i2c` group or use sudo)
- Linux system with I2C devices (`/dev/i2c-*`)

### Install from source

```bash
cd /home/kmills/git/kjm_tools/python/edid

# Install dependencies with uv
uv sync

# Or install in editable mode
uv pip install -e .
```

### Dependencies

Automatically installed:

- `click>=8.0` - CLI framework
- `smbus2>=0.4.0` - I2C bus communication

### Permissions

To access I2C devices without sudo:

```bash
# Add your user to the i2c group
sudo usermod -a -G i2c $USER

# Log out and back in for changes to take effect
# Or reload groups in current session:
newgrp i2c
```

## Usage

### Discover I2C Buses

List available I2C buses and detect EDID presence:

```bash
uv run edid list
uv run edid list --verbose  # Show detailed scanning info

# Or use the helper script
./run.sh list
./run.sh list --verbose
```

Output:

```
Available I2C Buses:
==================================================
  Bus 0:   No EDID
  Bus 5: ✓ EDID detected
  Bus 8: ✓ EDID detected
==================================================
```

### Read EDID

Read complete EDID data from a device to a binary file:

```bash
uv run edid read 5 display.bin
uv run edid read 5 display.bin --verbose  # Show read progress

# Or use the helper script
./run.sh read 5 display.bin
```

Reads base block (128 bytes) plus all extension blocks automatically.

### Decode EDID

Decode EDID from a binary file:

```bash
# Basic information (default)
uv run edid decode display.bin

# Hexadecimal dump
uv run edid decode display.bin --level hex

# Detailed parsing with extensions
uv run edid decode display.bin --level deep

# Or use the helper script
./run.sh decode display.bin --level basic
```

**Decode Levels:**

- `hex` - Raw hexadecimal dump with ASCII sidebar
- `basic` - Manufacturer, model, resolution, refresh rate, screen size
- `deep` - All timing descriptors, CEA-861 extensions, full details

Example output (basic):

```
======================================================================
EDID BASIC INFORMATION
======================================================================

Manufacturer: SAM
Product Code: 0x0C12
Serial Number: 1234567
Manufactured: Week 42, 2023
EDID Version: 1.4

Display Type: Digital
Screen Size: 62 x 34 cm
Diagonal: 27.6 inches
Gamma: 2.20

Display Name: SAMSUNG LCD

Preferred Timing (Detailed Descriptor):
  Resolution: 2560 x 1440
  Refresh Rate: 59.95 Hz
  Pixel Clock: 241.50 MHz

Extension Blocks: 1
======================================================================
```

### Write EDID

Write EDID data from a file to a device:

```bash
uv run edid write 5 display.bin
uv run edid write 5 display.bin --verbose  # Show write progress

# Or use the helper script
./run.sh write 5 display.bin
```

**Safety features:**

- Validates EDID structure before writing
- Automatically creates backup in `~/.edid-backups/`
- Recalculates checksums
- Writes in page-aligned chunks with delays
- Verifies write by reading back

⚠️ **WARNING**: Writing invalid EDID can make your display unusable!

### Validate EDID

Compare device EDID with a reference file:

```bash
uv run edid validate 5 display.bin
uv run edid validate 5 display.bin --verbose  # Show differences

# Or use the helper script
./run.sh validate 5 display.bin
```

Returns:

- Exit code 0 if match
- Exit code 1 if mismatch (shows byte differences with --verbose)

### Test Write Capability

Test if a device is writable:

```bash
uv run edid test-write 5
uv run edid test-write 5 --verbose  # Show detailed test process

# Or use the helper script
./run.sh test-write 5
```

**How it works:**

1. Creates automatic backup
2. Finds safe byte (unused descriptor padding or standard timing)
3. Writes test value (XOR 0xFF)
4. Verifies write
5. Restores original value
6. Verifies restoration

⚠️ **WARNING**: This temporarily modifies EDID data. While safe bytes are used, there is inherent risk. A backup is always created.

## Architecture

### Module Structure

```
edid/
├── __init__.py       # Package initialization
├── cli.py            # Click-based CLI interface
├── i2c.py            # I2C bus operations (read, write, backup)
├── parser.py         # EDID parsing and decoding
└── validator.py      # EDID validation and checksum
```

### Key Components

**validator.py:**

- `validate_checksum()` - Verify EDID block checksums (sum mod 256 == 0)
- `validate_header()` - Check magic bytes (00 FF FF FF FF FF FF 00)
- `validate_structure()` - Complete EDID validation
- `find_safe_test_byte()` - Locate unused bytes for write testing
- `calculate_checksum()` - Compute correct checksum
- `recalculate_checksums()` - Update all block checksums

**parser.py:**

- `decode_hex()` - Hexadecimal dump formatter
- `decode_basic()` - Extract key information
- `decode_deep()` - Detailed parsing with extensions
- `decode_manufacturer_id()` - 3-letter manufacturer code
- `decode_product_info()` - Product details
- `decode_detailed_timing()` - Parse timing descriptors
- `decode_cea861_block()` - CEA-861 extension parsing

**i2c.py:**

- `discover_buses()` - Scan for I2C devices
- `read_edid()` - Read complete EDID with extensions
- `write_edid()` - Write with page alignment and verification
- `backup_edid()` - Create timestamped backup
- `test_writable()` - Safe write capability test
- `validate_device_matches_file()` - Byte-by-byte comparison

**cli.py:**

- Six subcommands: `list`, `read`, `decode`, `write`, `validate`, `test-write`
- Global `--verbose` flag support
- Comprehensive error handling

## Technical Details

### EDID Structure

- **Base block**: 128 bytes
  - Header: `00 FF FF FF FF FF FF 00`
  - Manufacturer ID, product code, serial number
  - Display parameters, chromaticity
  - Standard and detailed timings
  - Extension count at byte 126
  - Checksum at byte 127

- **Extension blocks**: 128 bytes each
  - CEA-861: HDMI/consumer electronics (tag 0x02)
  - DisplayID: Advanced features (tag 0x70)
  - Each with own checksum

### I2C Communication

- **Address**: 0x50 (standard EDID address)
- **Read**: 32-byte chunks for reliability
- **Write**: 16-byte pages with 10ms delays
- **Devices**: `/dev/i2c-0` through `/dev/i2c-9` (typically)

### Safety Mechanisms

1. **Checksum validation**: All blocks verified (sum mod 256 must equal 0)
2. **Structure validation**: Header, size, extension count checks
3. **Automatic backups**: Timestamped files in `~/.edid-backups/`
4. **Write verification**: Read back and compare after write
5. **Safe byte detection**: Uses unused descriptor padding or standard timing slots
6. **Page-aligned writes**: EEPROM-compatible with delays
7. **Error handling**: Descriptive messages with recovery suggestions

### Safe Bytes for Write Testing

Priority order:

1. **Dummy descriptor padding** (bytes 72-89 when descriptor starts with 0x00 0x00)
2. **Unused standard timing** (bytes 38-53 when value is 0x01 0x01)

Avoids critical areas:

- Header (bytes 0-7)
- Product info (bytes 8-17)
- Version (bytes 18-19)
- Checksum (byte 127)
- Active timing descriptors

## Backups

Backups are automatically created in `~/.edid-backups/` with format:

```
edid_bus{N}_{YYYYMMDD}_{HHMMSS}.bin
```

Example:

```
edid_bus5_20231215_143022.bin
```

Backups are never automatically deleted. Manage manually if needed.

## Troubleshooting

### Permission Denied

```
Error: Permission denied accessing /dev/i2c-5
```

**Solution**: Add user to i2c group or use sudo:

```bash
sudo usermod -a -G i2c $USER
# Log out and back in
```

### Bus Not Found

```
Error: I2C bus 5 not found
```

**Solution**: Use `edid list` to discover available buses.

### No EDID Detected

```
No EDID devices detected on any bus
```

**Possible causes:**

- Display not connected or powered off
- Wrong bus number
- Display doesn't support I2C EDID access
- Hardware/driver issues

**Solution**: Check connections, try different buses, check `dmesg` for I2C errors.

### Write Verification Failed

```
Write verification failed! Data read back does not match.
```

**Possible causes:**

- Device is write-protected
- Hardware write-protect pin enabled
- EEPROM requires different timing

**Solution**: Check device datasheet, verify write-protect pins, use backup to restore.

### No Safe Test Byte Found

```
No safe test byte found in EDID
```

**Solution**: The EDID has no unused areas. Skip write testing or accept the risk of testing on used bytes.

## Examples

### Complete Workflow

```bash
# 1. Discover buses
uv run edid list

# 2. Read EDID from bus 5
uv run edid read 5 original.bin

# 3. Decode to verify content
uv run edid decode original.bin --level deep

# 4. Test if writable
uv run edid test-write 5 --verbose

# 5. Write modified EDID (if needed)
uv run edid write 5 modified.bin --verbose

# 6. Validate write
uv run edid validate 5 modified.bin
```

### Backup and Restore

```bash
# Backup current EDID
uv run edid read 5 backup_$(date +%Y%m%d).bin

# Later, restore from backup
uv run edid write 5 backup_20231215.bin
```

### Compare EDIDs

```bash
# Read from device
uv run edid read 5 device.bin

# Compare with reference
uv run edid validate 5 reference.bin --verbose
```

## Version

Current version: 0.1.0

## License

See repository LICENSE file.

## Author

Kyle Mills (@mgfarmer)

## Contributing

This is a personal tool project. Use at your own risk.

## Disclaimer

⚠️ **WARNING**: Modifying EDID data can potentially damage displays or make them unusable. Always:

- Create backups before writing
- Validate EDID files before writing
- Understand what you're modifying
- Have a way to restore original EDID

The authors are not responsible for any damage caused by using this tool.
