#!/bin/bash
# Fetch /etc/default/grub samples from distro package repositories

OUTPUT_DIR="$(dirname "$0")/sample_grub_configs"
mkdir -p "$OUTPUT_DIR"

echo "Fetching GRUB configs from distro package repositories..."
echo "Output directory: $OUTPUT_DIR"
echo ""

# Function to fetch a file with fallback URLs
fetch_grub() {
    local name=$1
    shift
    local urls=("$@")
    # Download under a temporary name; the checksum in the final name must be
    # derived from the downloaded content, not from the download attempt.
    local tmp="$OUTPUT_DIR/.${name}.tmp"

    echo -n "[$name] ... "

    for url in "${urls[@]}"; do
        if curl -sSfL --max-time 10 "$url" -o "$tmp" 2>/dev/null; then
            # Verify it looks like a grub config
            if grep -q "GRUB_" "$tmp" 2>/dev/null; then
                local checksum
                checksum=$(sha256sum "$tmp" | cut -c1-8 | tr '[:lower:]' '[:upper:]')
                mv -f "$tmp" "$OUTPUT_DIR/29991213-000000-${checksum}.${name}.bak"
                echo "✓ got it"
                return 0
            fi
        fi
    done

    echo "✗ failed"
    rm -f "$tmp"
    return 1
}

# Ubuntu - from Launchpad
fetch_grub "ubuntu-22.04" \
    "https://git.launchpad.net/ubuntu/+source/grub2/plain/debian/default-grub?h=applied/ubuntu/jammy-devel" \
    "https://git.launchpad.net/ubuntu/+source/grub2/plain/debian/default-grub?h=ubuntu/jammy"

fetch_grub "ubuntu-24.04" \
    "https://git.launchpad.net/ubuntu/+source/grub2/plain/debian/default-grub?h=applied/ubuntu/noble-devel" \
    "https://git.launchpad.net/ubuntu/+source/grub2/plain/debian/default-grub?h=ubuntu/noble"

# Debian
fetch_grub "debian-12" \
    "https://salsa.debian.org/grub-team/grub/-/raw/debian/unstable/debian/default-grub" \
    "https://sources.debian.org/data/main/g/grub2/2.06-13/debian/default-grub"

# Fedora
fetch_grub "fedora-40" \
    "https://src.fedoraproject.org/rpms/grub2/raw/f40/f/grub.default" \
    "https://src.fedoraproject.org/rpms/grub2/raw/rawhide/f/grub.default"

# Arch
fetch_grub "arch" \
    "https://gitlab.archlinux.org/archlinux/packaging/packages/grub/-/raw/main/grub.default" \
    "https://raw.githubusercontent.com/archlinux/svntogit-packages/packages/grub/trunk/grub.default"

# openSUSE
fetch_grub "opensuse-tumbleweed" \
    "https://raw.githubusercontent.com/openSUSE/grub2/master/grub.default"

# CentOS/RHEL
fetch_grub "centos-stream-9" \
    "https://gitlab.com/redhat/centos-stream/rpms/grub2/-/raw/c9s/grub.default" \
    "https://gitlab.com/redhat/centos-stream/rpms/grub2/-/raw/main/grub.default"

echo ""
echo "Done! Collected configs:"
count=$(ls -1 "$OUTPUT_DIR"/*.bak 2>/dev/null | wc -l)
echo "$count"
echo ""
if [ "$count" -gt 0 ]; then
    echo "Files are in: $OUTPUT_DIR"
    echo ""
    echo "To install them for testing, run: ./install_grub_samples.sh"
else
    echo "No configs collected. Check your internet connection."
fi
