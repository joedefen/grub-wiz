#!/bin/bash
# Make the checksum component of every sample filename match its content.
#
# Backup names are YYYYMMDD-HHMMSS-{8-hex-checksum}.{tag}.bak and the
# application compares that checksum with the file content.  Hand-built samples
# used a placeholder (00000000) or a random value, so rewrite each name with the
# real leading 8 hex digits of the file's SHA-256.

cd "$(dirname "$0")/sample_grub_configs" || exit 1

for f in *.bak; do
    if [ -f "$f" ]; then
        # Leading 8 uppercase hex digits of the real content checksum
        checksum=$(sha256sum "$f" | cut -c1-8 | tr '[:lower:]' '[:upper:]')
        newname=$(echo "$f" | sed -E "s/^([0-9]{8}-[0-9]{6})-[0-9A-Fa-f]{8}\./\1-${checksum}./")
        if [ "$f" != "$newname" ]; then
            echo "Renaming: $f -> $newname"
            mv "$f" "$newname"
        fi
    fi
done

echo "Done! Files now:"
ls -1 *.bak
