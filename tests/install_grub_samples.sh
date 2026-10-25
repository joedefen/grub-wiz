#!/bin/bash
# Copy collected GRUB sample configs to ~/.config/grub-wiz/backups/ for testing

set -e

SAMPLES_DIR="$(dirname "$0")/sample_grub_configs"
BACKUP_DIR="$HOME/.config/grub-wiz"

# Check if samples exist
if [ ! -d "$SAMPLES_DIR" ] || [ -z "$(ls -A "$SAMPLES_DIR"/*.bak 2>/dev/null)" ]; then
    echo "Error: No sample configs found in $SAMPLES_DIR"
    echo "Run ./fetch_grub_samples.sh first"
    exit 1
fi

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "Installing GRUB sample configs for testing..."
echo "Source: $SAMPLES_DIR"
echo "Target: $BACKUP_DIR"
echo ""

# Copy all .bak files
count=0
for file in "$SAMPLES_DIR"/*.bak; do
    if [ -f "$file" ]; then
        basename=$(basename "$file")
        echo "  Installing: $basename"
        cp "$file" "$BACKUP_DIR/"
        count=$((count + 1))
    fi
done

echo ""
echo "✓ Installed $count sample configs"
echo ""
echo "You can now:"
echo "  1. Run grub-wiz"
echo "  2. Press 'R' to enter Restore screen"
echo "  3. Test each distro config by selecting and restoring it"
echo "  4. Check for 'Unvalidated Params' and validation warnings"
