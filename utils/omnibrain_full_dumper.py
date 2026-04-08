# -*- coding: utf-8 -*-
import os

# CONFIG
TARGET_DIR = "."
ENCODINGS = ["utf-8", "latin1", "cp1252"]
MAX_FILE_SIZE_MB = 2  # Skip files bigger than 2 MB

def read_file_safe(filepath):
    for enc in ENCODINGS:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return f.read()
        except Exception:
            continue
    return f"<< Could not read {filepath} with common encodings >>"

def dump_all_files(target_dir):
    output_lines = []

    for root, _, files in os.walk(target_dir):
        for file in files:
            full_path = os.path.join(root, file)
            try:
                file_size_mb = os.path.getsize(full_path) / (1024 * 1024)
                if file_size_mb > MAX_FILE_SIZE_MB:
                    print(f"⚠️ Skipping large file: {file} ({file_size_mb:.2f} MB)")
                    continue
            except Exception:
                continue

            rel_path = os.path.relpath(full_path, target_dir)
            print(f"📄 Reading: {rel_path}")

            output_lines.append("\n\n==============================")
            output_lines.append(f"FILE: {rel_path}")
            output_lines.append("==============================")

            content = read_file_safe(full_path)
            output_lines.append(content)

    return "\n".join(output_lines)

if __name__ == "__main__":
    if not os.path.isdir(TARGET_DIR):
        print(f"ERROR: Folder '{TARGET_DIR}' not found.")
    else:
        dump = dump_all_files(TARGET_DIR)
        with open("omnibrain_full_dump.txt", "w", encoding="utf-8") as f:
            f.write(dump)
        print("\n✅ Dump complete.")
