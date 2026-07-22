#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
  echo "usage: verify_restore.sh <encrypted-bundle.age> <age-identity-file> <restore-dir>" >&2
  exit 2
fi

encrypted_bundle="$1"
identity_file="$2"
restore_dir="$3"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

mkdir -p "$restore_dir"
if find "$restore_dir" -mindepth 1 -print -quit | grep -q .; then
  echo "restore directory must be empty" >&2
  exit 1
fi
age -d -i "$identity_file" -o "$work_dir/bundle.tar.gz" "$encrypted_bundle"
tar -xzf "$work_dir/bundle.tar.gz" -C "$work_dir"
protected_archive="$(find "$work_dir" -maxdepth 1 -name 'protected-corpus-*.tar.gz' -print -quit)"
protected_manifest="$(find "$work_dir" -maxdepth 1 -name 'protected-corpus-*.sha256' -print -quit)"
if [ -z "$protected_archive" ] || [ -z "$protected_manifest" ]; then
  echo "protected corpus archive or manifest missing" >&2
  exit 1
fi
tar -xzf "$protected_archive" -C "$restore_dir"
(cd "$restore_dir" && sha256sum -c "$protected_manifest")
echo "protected corpus restore verified"
