# EDID Manager

## Features

- ✅ read an EDID to a binary file
- ✅ decode an EDID data block from a device of binary file into something human readable
- ✅ write a binary file to an EDID device (verifying that the binary file is a valid EDID dataset)
- ✅ validate that an EDID device matches a binary file
- ✅ check that an EDID device is writable at all (using safe test bytes, with backup and restore)
- ✅ discover available I2C buses and detect EDID presence

## Implementation Status: COMPLETE ✅

### Architecture

**Modules:**

- `edid/validator.py` - EDID validation (checksums, header, structure, safe byte detection)
- `edid/parser.py` - EDID decoding (hex dump, basic info, deep parsing with CEA-861 extensions)
- `edid/i2c.py` - I2C operations (read, write, backup, discovery, write testing)
- `edid/cli.py` - CLI interface with 6 subcommands

**Dependencies:**

- `click>=8.0` - CLI framework with subcommand support
- `smbus2>=0.4.0` - I2C bus access for Python 3.x

**Entry Points:**

- Command: `edid` (via pyproject.toml scripts)
- Module: `edid.cli:main`

### CLI Commands

1. **list** - Discover I2C buses and detect EDID presence at address 0x50
2. **read** `<bus> <file>` - Read complete EDID including all extensions to binary file
3. **decode** `<file> --level [hex|basic|deep]` - Parse and display EDID in human-readable format
4. **write** `<bus> <file>` - Write validated EDID to device with auto-backup and verification
5. **validate** `<bus> <file>` - Compare device EDID with file byte-by-byte
6. **test-write** `<bus>` - Test device writability using safe bytes with backup/restore

All commands support `--verbose` flag for detailed operation logging.

### Safety Features Implemented

- **Automatic backups** before any write operation (saved to `~/.edid-backups/` with timestamps)
- **Checksum validation** for all EDID blocks (base + extensions)
- **Structure validation** (header magic bytes, size checks, extension count verification)
- **Write verification** by reading back and comparing data
- **Safe byte detection** for write testing (unused descriptor padding or standard timing slots)
- **Page-aligned writes** with 10ms delays for EEPROM compatibility
- **Comprehensive error handling** with actionable messages for permissions, device access, I2C failures

### Technical Details

**I2C Access:**

- Standard EDID address: 0x50
- Bus format: numeric only (e.g., `5` for `/dev/i2c-5`)
- Read method: 32-byte chunks for base block and extensions
- Write method: 16-byte pages with 10ms delays
- Automatic extension detection from byte 126 of base block

**EDID Parsing:**

- **Hex level**: Raw hexadecimal dump with ASCII sidebar
- **Basic level**: Manufacturer, model, serial, resolution, refresh rate, display size
- **Deep level**: All timing descriptors, CEA-861 extension parsing (audio/video blocks), chromaticity

**Write Testing:**

- Finds safe bytes in unused descriptors (bytes 72-89 when dummy) or unused standard timings (0x0101)
- Creates backup before test
- Writes complementary value (XOR 0xFF)
- Verifies write succeeded
- Restores original value
- Verifies restoration
- Documents inherent risk

### Design Decisions Made

1. **Extension handling**: Auto-read all extensions based on byte 126 count ✅
2. **Safe byte strategy**: Detect unused descriptor padding, fall back to standard timing slots ✅
3. **Bus discovery**: Added `list` command scanning `/dev/i2c-*` ✅
4. **Bus format**: Numeric only (e.g., `5` not `/dev/i2c-5`) ✅
5. **Output format**: Human-readable only (no JSON) ✅
6. **Backup retention**: No automatic cleanup ✅
7. **Verbose mode**: Global `--verbose` flag on all commands ✅
8. **Write safety**: No force flag required (trust the user) ✅

### Installation & Usage

See README.md for complete installation and usage instructions.
