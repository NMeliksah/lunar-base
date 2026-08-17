#!/usr/bin/env python3
"""
Dump master data binary to individual JSON files per table.

Decrypts the MasterMemory binary (.bin.e), decompresses each LZ4 table,
deserializes the positional msgpack rows, maps column indices to field
names using the bundled schemas.json, and writes each table as a JSON file.

Output mirrors the master_data/ directory layout:
  <output_dir>/<EntityClassName>Table.json   (named columns)
  <output_dir>/<snake_name>.json             (fallback for unrecognized tables)

Requires: pip install pycryptodome msgpack lz4

Usage:
  python dump_masterdata.py
  python dump_masterdata.py --output /tmp/dump
  python dump_masterdata.py --key KEY_HEX --iv IV_HEX
  python dump_masterdata.py --key-file key.bin --iv-file iv.bin
"""

import argparse
import json
import os
import struct
import sys

import lz4.block
import msgpack
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


DEFAULT_INPUT = os.path.join("server", "assets", "release", "20240404193219.bin.e")
DEFAULT_OUTPUT = "master_data"
DEFAULT_KEY = "36436230313332314545356536624265"
DEFAULT_IV  = "45666341656634434165356536446141"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMAS_PATH = os.path.join(SCRIPT_DIR, "schemas.json")


def load_schemas():
    """Load column-name mappings from the bundled schemas.json.

    Returns dict: snake_case_name -> (class_name, [(key_idx, type_str, field_name)])
    """
    with open(SCHEMAS_PATH) as f:
        raw = json.load(f)
    schema = {}
    for snake, entry in raw.items():
        cols = [(idx, typ, name) for idx, typ, name in entry["columns"]]
        schema[snake] = (entry["class"], cols)
    return schema


def read_lz4_ext_header(ext_data):
    tag = ext_data[0]
    if tag == 0xd2:
        return struct.unpack('>i', ext_data[1:5])[0], ext_data[5:]
    if tag == 0xce:
        return struct.unpack('>I', ext_data[1:5])[0], ext_data[5:]
    if tag <= 0x7f:
        return tag, ext_data[1:]
    raise ValueError(f"Unexpected tag 0x{tag:02x} in LZ4 ext header")


def decompress_table(data_blob, offset, length):
    """Decompress a single table blob, returning the deserialized rows."""
    blob = data_blob[offset:offset + length]
    obj = msgpack.unpackb(blob, raw=False, strict_map_key=False)

    if isinstance(obj, msgpack.ExtType) and obj.code == 99:
        ulen, lz4_data = read_lz4_ext_header(obj.data)
        decompressed = lz4.block.decompress(lz4_data, uncompressed_size=ulen)
        return msgpack.unpackb(decompressed, raw=False, strict_map_key=False)

    # Small/empty tables may be stored without LZ4 compression
    if isinstance(obj, list):
        return obj
    return [obj]


def rows_to_dicts(rows, columns):
    """Convert positional row arrays to named-key dicts using the column schema."""
    col_map = {idx: name for idx, _typ, name in columns}
    result = []
    for row in rows:
        if isinstance(row, list):
            d = {}
            for i, val in enumerate(row):
                key = col_map.get(i, f"Key{i}")
                d[key] = val
            result.append(d)
        else:
            result.append(row)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Dump master data binary to JSON files per table."
    )

    key_group = parser.add_mutually_exclusive_group()
    key_group.add_argument("--key", default=DEFAULT_KEY,
                           help="AES key as hex string (default: built-in)")
    key_group.add_argument("--key-file", help="Path to raw key file (16 or 32 bytes)")

    iv_group = parser.add_mutually_exclusive_group()
    iv_group.add_argument("--iv", default=DEFAULT_IV,
                          help="AES IV as hex string (default: built-in)")
    iv_group.add_argument("--iv-file", help="Path to raw IV file (16 bytes)")

    parser.add_argument("--input", default=DEFAULT_INPUT,
                        help=f"Input .bin.e file (default: {DEFAULT_INPUT})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Output directory (default: {DEFAULT_OUTPUT})")

    args = parser.parse_args()

    # Load key
    if args.key_file:
        with open(args.key_file, "rb") as f:
            key = f.read()
    else:
        key = bytes.fromhex(args.key)
    if len(key) not in (16, 32):
        print(f"ERROR: AES key must be 16 or 32 bytes, got {len(key)}", file=sys.stderr)
        sys.exit(1)

    # Load IV
    if args.iv_file:
        with open(args.iv_file, "rb") as f:
            iv = f.read()
    else:
        iv = bytes.fromhex(args.iv)
    if len(iv) != 16:
        print(f"ERROR: AES IV must be 16 bytes, got {len(iv)}", file=sys.stderr)
        sys.exit(1)

    # Load entity schemas
    print(f"Loading schemas from {SCHEMAS_PATH}...")
    schema = load_schemas()
    print(f"  {len(schema)} entity definitions loaded")

    # Read and decrypt
    print(f"Reading {args.input}...")
    with open(args.input, "rb") as f:
        encrypted = f.read()
    print(f"  Encrypted size: {len(encrypted)} bytes")

    aes_bits = len(key) * 8
    print(f"Decrypting (AES-{aes_bits}-CBC)...")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    try:
        decrypted = unpad(cipher.decrypt(encrypted), AES.block_size)
    except ValueError as e:
        print(f"ERROR: Decryption failed: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"  Decrypted size: {len(decrypted)} bytes")

    # Parse header
    print("Parsing MasterMemory header...")
    try:
        toc = msgpack.unpackb(decrypted, raw=False, strict_map_key=False)
        data_blob = b""
    except msgpack.ExtraData as e:
        toc = e.unpacked
        data_blob = e.extra
    print(f"  {len(toc)} tables, data blob: {len(data_blob)} bytes")

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    # Dump tables
    print(f"\nDumping tables to {args.output}/...")
    dumped = 0
    failed = 0
    fallback = 0

    for tname, (offset, length) in sorted(toc.items()):
        try:
            rows = decompress_table(data_blob, offset, length)

            if tname in schema:
                class_name, columns = schema[tname]
                filename = f"{class_name}Table.json"
                dicts = rows_to_dicts(rows, columns)
            else:
                filename = f"{tname}.json"
                dicts = rows
                fallback += 1

            filepath = os.path.join(args.output, filename)
            with open(filepath, "w") as f:
                json.dump(dicts, f, indent=2, ensure_ascii=False)
                f.write("\n")

            dumped += 1
        except Exception as ex:
            print(f"  ERROR: {tname}: {ex}", file=sys.stderr)
            failed += 1

    print(f"\n  Dumped {dumped} tables ({fallback} without schema, {failed} failed)")
    print(f"  Output: {os.path.abspath(args.output)}/")


if __name__ == "__main__":
    main()
