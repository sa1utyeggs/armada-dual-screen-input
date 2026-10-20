#!/bin/bash
# Offline-only: builds a module in an isolated workspace; never loads anything.
set -euo pipefail

cache=${KERNEL_CACHE:-/kernel-cache}
recipe=${KERNEL_RECIPE:-/kernel-recipe}
source_dir=${MODULE_SOURCE:-/module-source}
workspace=${MODULE_WORK:-/module-work}
output=${MODULE_OUTPUT:-/output}
kernel="$workspace/linux-7.2.6"
module="$workspace/module"
mkdir -p "$workspace" "$output"
test "$(uname -m)" = aarch64
test "$(sha256sum "$cache/linux-7.2.6.tar.xz" | cut -d' ' -f1)" = \
    039aef84f2b0994aeda3f4fcfc3d02ec9d7a9bbb9020ea264c43f446c860f606

if [[ ! -e "$workspace/kernel-prepared" ]]; then
    test ! -e "$kernel"
    tar -xf "$cache/linux-7.2.6.tar.xz" -C "$workspace"
    applied=0
    while IFS= read -r line; do
        line=${line%%#*}
        patch_name=$(printf '%s' "$line" | awk '{$1=$1};1')
        [[ -n "$patch_name" ]] || continue
        patch -d "$kernel" -p1 --batch --forward -F0 --no-backup-if-mismatch \
            --silent < "$recipe/patches/$patch_name"
        applied=$((applied + 1))
    done < "$recipe/patches/series"
    test "$applied" = 193
    cp "$output/running.config" "$kernel/.config"
    make -C "$kernel" -j4 LOCALVERSION= olddefconfig modules_prepare
    test "$(make -s -C "$kernel" LOCALVERSION= kernelrelease)" = 7.2.6
    cmp "$output/running.config" "$kernel/.config"
    printf '%s\n' "$applied" > "$workspace/kernel-prepared"
fi

python3 - "$kernel" "$source_dir" <<'PY'
from pathlib import Path
import hashlib, json, sys
kernel, source = map(Path, sys.argv[1:])
origin = json.loads((source / 'source.json').read_text())
actual = hashlib.sha256((kernel / 'drivers/input/touchscreen/edt-ft5x06.c').read_bytes()).hexdigest()
assert actual == origin['patched_reference_source_sha256'], 'Reference driver changed'
PY

mkdir -p "$module"
cp "$source_dir/module/Makefile" "$source_dir/module/armada_thor_ft5452.c" "$module/"
make -C "$kernel" -j4 M="$module" LOCALVERSION= W=1 armada_thor_ft5452.o
python3 "$source_dir/export_subset.py" --kernel "$kernel" \
    --object "$module/armada_thor_ft5452.o" \
    --live-exports "$output/host-exports.json" --out "$output"
cp "$output/Module.symvers" "$kernel/Module.symvers"
make -C "$kernel" -j4 M="$module" LOCALVERSION= W=1 modules
cp "$module/armada_thor_ft5452.ko" "$output/"
strip --strip-debug "$output/armada_thor_ft5452.ko"
chmod 0644 "$output/armada_thor_ft5452.ko"
modinfo "$output/armada_thor_ft5452.ko" > "$output/modinfo.txt"
readelf -h "$output/armada_thor_ft5452.ko" > "$output/elf-header.txt"
objdump -dr "$module/armada_thor_ft5452.o" > "$output/module-disassembly.txt"
gcc --version > "$output/compiler.txt"
printf '%s\n' 'Module compiled only; no insmod, bind, boot or device write performed.'
