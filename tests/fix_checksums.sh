#!/bin/bash
# Make the checksum component of every sample filename match its content.
#
# Current backup names are YYYYMMDD-HHMMSS-s{6-hex}.{tag}.bak (the tag is
# optional); the samples in this directory predate that scheme and use the
# legacy YYYYMMDD-HHMMSS-{8-hex}.{tag}.bak form, which the application still
# reads and restores.  Either shape is rewritten in place so the checksum a
# filename claims really is the leading hex digits of the file's SHA-256.

cd "$(dirname "$0")/sample_grub_configs" || exit 1

for f in *.bak; do
    if [ -f "$f" ]; then
        if [[ "$f" =~ ^[0-9]{8}-[0-9]{6}-s[0-9A-Fa-f]{6} ]]; then
            # Current shape: six digits behind a lower-case "s"
            checksum=$(sha256sum "$f" | cut -c1-6 | tr '[:lower:]' '[:upper:]')
            newname=$(echo "$f" | sed -E "s/^([0-9]{8}-[0-9]{6})-s[0-9A-Fa-f]{6}/\1-s${checksum}/")
        else
            # Legacy shape: eight digits, mandatory tag
            checksum=$(sha256sum "$f" | cut -c1-8 | tr '[:lower:]' '[:upper:]')
            newname=$(echo "$f" | sed -E "s/^([0-9]{8}-[0-9]{6})-[0-9A-Fa-f]{8}/\1-${checksum}/")
        fi
        if [ "$f" != "$newname" ]; then
            echo "Renaming: $f -> $newname"
            mv "$f" "$newname"
        fi
    fi
done

echo "Done! Files now:"
ls -1 *.bak
