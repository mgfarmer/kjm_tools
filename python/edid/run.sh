#!/bin/bash
# Helper script to run EDID Manager during development with uv

# Change to script directory
cd "$(dirname "$0")"

# Check if we need i2c group access and don't have it yet
if ! groups | grep -q '\bi2c\b' && getent group i2c | grep -q "$(whoami)"; then
    # We're in the i2c group but current session doesn't have it - use sg
    exec sg i2c -c "$0 $*"
fi

# Run the EDID manager with uv, passing all arguments through
uv run python -m edid.cli "$@"
