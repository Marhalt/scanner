# Scanner

Part of a suite of tools designed to clean up `.txt` files for LLM fine-tuning.
Pipeline order: `name_clean.py` → **`scanner.py`** → focused cleanup.

## What it does

Scanner reads every `.txt` file in a given directory and writes a cleaned,
ASCII-ready copy into a subfolder. For each file it:

1. **Detects the real encoding** (via [charset-normalizer](https://pypi.org/project/charset-normalizer/),
   with an optional [chardet](https://pypi.org/project/chardet/) fallback) and decodes it.
   A file that cannot be decoded cleanly falls back to inserting U+FFFD markers
   rather than crashing.
2. **Normalizes newlines** — `CRLF` and lone `CR` both become `LF` (replaces `dos2unix`).
3. **Re-decodes stray C1 control bytes** as Windows-1252.
4. **Replaces non-ASCII Unicode characters** with their closest ASCII equivalent
   (curly quotes become straight quotes, em dashes become `--`, and so on).
5. **Strips diacritics** from remaining accented Latin letters (`é` → `e`).
6. Optionally **repairs U+FFFD** with a local LLM (`-llm`).
7. Optionally **blanks any remaining non-ASCII** character to a space (`-force`).

The original files are never modified. Each cleaned file is written, with its
**original modification time preserved**, into one of two subfolders of the
target directory:

- **`clean/`** — no non-ASCII characters left.
- **`weird/`** — one or more non-ASCII characters remain; needs a look. (`-save`
  or `-force` sends everything to `clean/` instead.)

This tool absorbs what `normalize.py` and `dos2unix --keepdate` used to do.

## Command-line options

```
python scanner.py [directory] [-llm] [-save] [-force] [-r]
```

- **directory** — folder containing `.txt` files. If omitted, the program prompts for it.
- **-llm** — when a U+FFFD replacement character is found, call a local LLM served by
  [LM Studio](https://lmstudio.ai) and ask it to infer the intended character from context.
- **-save** — route every file to `clean/` even if weird characters remain.
- **-force** — replace every remaining non-ASCII character with a space (implies everything lands in `clean/`).
- **-r**, **--recursive** — recurse into subdirectories (the `clean/` and `weird/`
  trees mirror the input layout; those folders are never re-scanned).

## Requirements

- Python 3
- [requests](https://pypi.org/project/requests/) (`pip install requests`)
- [charset-normalizer](https://pypi.org/project/charset-normalizer/) (`pip install charset-normalizer`)
- [chardet](https://pypi.org/project/chardet/) — optional, used as a secondary encoding detector
- [LM Studio](https://lmstudio.ai) running locally on port 1234 (only required for `-llm` mode)
