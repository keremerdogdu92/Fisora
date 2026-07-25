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
if [ ! -f "$work_dir/postgres.sql" ] || [ ! -f "$work_dir/protected-corpus.tar" ] || [ ! -f "$work_dir/SHA256SUMS" ]; then
  echo "postgres.sql, protected-corpus.tar, or SHA256SUMS missing" >&2
  exit 1
fi
(cd "$work_dir" && sha256sum -c SHA256SUMS)
cp "$work_dir/postgres.sql" "$restore_dir/postgres.sql"
tar -xf "$work_dir/protected-corpus.tar" -C "$restore_dir"
echo "backup package hashes and protected corpus restore verified"
