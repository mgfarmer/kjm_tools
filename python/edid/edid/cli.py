"""CLI interface for EDID Manager."""

import sys
import click
from pathlib import Path

from . import __version__
from .i2c import (
    discover_buses,
    read_edid,
    write_edid,
    test_writable,
    validate_device_matches_file,
)
from .parser import decode_hex, decode_basic, decode_deep
from .validator import validate_structure, recalculate_checksums


@click.group()
@click.version_option(version=__version__)
@click.pass_context
def cli(ctx):
    """EDID Manager - CLI tool for managing EDID data via I2C devices.

    This tool allows you to read, decode, write, and validate EDID data
    from display devices connected via I2C.

    Common I2C bus numbers are 0-9. Use 'edid list' to discover available buses.
    """
    # Store context for subcommands
    ctx.ensure_object(dict)


@cli.command()
@click.option(
    "--verbose", "-v", is_flag=True, help="Show detailed scanning information"
)
def list(verbose):
    """List available I2C buses and detect EDID presence.

    Scans /dev/i2c-* devices and probes for EDID at address 0x50.
    """
    try:
        buses = discover_buses(verbose=verbose)

        if not buses:
            click.echo("No I2C buses found.")
            click.echo("\nMake sure:")
            click.echo("  - I2C is enabled on your system")
            click.echo("  - You have permission to access I2C devices")
            click.echo("    (add user to 'i2c' group or run with sudo)")
            return

        click.echo("\nAvailable I2C Buses:")
        click.echo("=" * 50)

        edid_found = False
        for bus_num, has_edid in buses:
            status = "✓ EDID detected" if has_edid else "  No EDID"
            click.echo(f"  Bus {bus_num}: {status}")
            if has_edid:
                edid_found = True

        click.echo("=" * 50)

        if edid_found:
            click.echo("\nUse 'edid read <bus> <output-file>' to read EDID data.")
        else:
            click.echo("\nNo EDID devices detected on any bus.")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("bus", type=int)
@click.argument("output", type=click.Path())
@click.option("--verbose", "-v", is_flag=True, help="Show detailed read information")
def read(bus, output, verbose):
    """Read EDID from I2C device to file.

    Reads complete EDID including all extension blocks from the specified
    I2C bus and saves to a binary file.

    BUS: I2C bus number (e.g., 5 for /dev/i2c-5)

    OUTPUT: Output file path for binary EDID data
    """
    try:
        edid_data = read_edid(bus, verbose=verbose)

        # Write to file
        output_path = Path(output)
        output_path.write_bytes(edid_data)

        if not verbose:
            click.echo(f"Read {len(edid_data)} bytes from bus {bus}")
        click.echo(f"Saved to: {output_path}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("input", type=click.Path(exists=True))
@click.option(
    "--level",
    "-l",
    type=click.Choice(["hex", "basic", "deep"], case_sensitive=False),
    default="basic",
    help="Decode level: hex (raw dump), basic (summary), deep (detailed)",
)
@click.option("--verbose", "-v", is_flag=True, help="Show verbose output")
def decode(input, level, verbose):
    """Decode EDID from binary file.

    Parses and displays EDID information in human-readable format.

    INPUT: Path to binary EDID file
    """
    try:
        # Read EDID file
        input_path = Path(input)
        edid_data = input_path.read_bytes()

        # Validate structure
        is_valid, message = validate_structure(edid_data)
        if not is_valid:
            click.echo(f"Warning: {message}", err=True)
            click.echo("Attempting to decode anyway...\n")

        # Decode based on level
        level_lower = level.lower()
        if level_lower == "hex":
            output = decode_hex(edid_data, verbose=verbose)
        elif level_lower == "basic":
            output = decode_basic(edid_data, verbose=verbose)
        elif level_lower == "deep":
            output = decode_deep(edid_data, verbose=verbose)
        else:
            click.echo(f"Unknown decode level: {level}", err=True)
            sys.exit(1)

        click.echo(output)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("bus", type=int)
@click.argument("input", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Show detailed write information")
def write(bus, input, verbose):
    """Write EDID from file to I2C device.

    Writes binary EDID data to the specified I2C bus device.
    Automatically creates a backup before writing and verifies the write.

    WARNING: Writing invalid EDID data can make your display unusable!

    BUS: I2C bus number (e.g., 5 for /dev/i2c-5)

    INPUT: Path to binary EDID file
    """
    try:
        # Read EDID file
        input_path = Path(input)
        edid_data = input_path.read_bytes()

        # Validate structure
        is_valid, message = validate_structure(edid_data)
        if not is_valid:
            click.echo(f"Error: Invalid EDID file - {message}", err=True)
            sys.exit(1)

        if verbose:
            click.echo(f"EDID file valid: {message}")

        # Recalculate checksums to ensure they're correct
        edid_array = bytearray(edid_data)
        recalculate_checksums(edid_array)
        edid_data = bytes(edid_array)

        if verbose:
            click.echo("Checksums recalculated")

        # Write to device (includes automatic backup)
        write_edid(bus, edid_data, verbose=verbose)

        if not verbose:
            click.echo(f"Successfully wrote {len(edid_data)} bytes to bus {bus}")
            click.echo("Backup created in ~/.edid-backups/")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("bus", type=int)
@click.argument("file", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Show detailed comparison")
def validate(bus, file, verbose):
    """Validate that EDID device matches a file.

    Reads EDID from the I2C device and compares it byte-by-byte with
    the specified file.

    BUS: I2C bus number (e.g., 5 for /dev/i2c-5)

    FILE: Path to binary EDID file for comparison
    """
    try:
        # Read file
        file_path = Path(file)
        file_data = file_path.read_bytes()

        # Validate file structure
        is_valid, message = validate_structure(file_data)
        if not is_valid:
            click.echo(f"Warning: File EDID invalid - {message}", err=True)

        # Compare with device
        matches, result_message = validate_device_matches_file(
            bus, file_data, verbose=verbose
        )

        if matches:
            click.echo(f"✓ {result_message}")
            sys.exit(0)
        else:
            click.echo(f"✗ {result_message}", err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("test-write")
@click.argument("bus", type=int)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed test information")
def test_write(bus, verbose):
    """Test if EDID device is writable.

    Attempts to write a test value to a safe byte, verify it, and restore
    the original value. Creates a backup before testing.

    WARNING: This test temporarily modifies EDID data. While it attempts to
    use safe bytes and restore original values, there is inherent risk.
    A backup will be created automatically.

    BUS: I2C bus number (e.g., 5 for /dev/i2c-5)
    """
    try:
        is_writable, message = test_writable(bus, verbose=verbose)

        if is_writable:
            click.echo(f"\n✓ {message}")
            click.echo("\nThe device appears to be writable.")
            click.echo("You can use 'edid write' to update the EDID.")
            sys.exit(0)
        else:
            click.echo(f"\n✗ {message}")
            click.echo("\nThe device does not appear to be writable.")
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def main():
    """Main entry point for CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
