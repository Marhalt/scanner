import os
import re
import argparse
import unicodedata
from collections import Counter
import requests

try:
    from charset_normalizer import from_bytes
except ImportError:  # pragma: no cover
    from_bytes = None

try:
    import chardet
except ImportError:  # pragma: no cover
    chardet = None

REPLACEMENT_CHAR = '�'
LM_STUDIO_URL = 'http://localhost:1234/v1/chat/completions'


def detect_encoding(data: bytes) -> str:
    if not data:
        return "utf-8"

    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    if from_bytes is not None:
        results = from_bytes(data)
        if results:
            best = results.best()
            if best and best.encoding:
                return best.encoding.lower()

    if chardet is not None:
        result = chardet.detect(data)
        if result and result.get("encoding"):
            return result["encoding"].lower()

    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # Windows-1252 is a superset of Latin-1 for printable characters.
    for enc in ("cp1252", "latin-1", "iso-8859-1"):
        try:
            data.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue

    return "utf-8"


def decode_bytes(raw):
    """Decode raw file bytes to text.

    Returns (text, detected_encoding, used_replacement). A truly broken file
    falls back to errors="replace", yielding U+FFFD characters that the -llm
    path (or the weird/ bucket) can then deal with.
    """
    detected = detect_encoding(raw)
    try:
        return raw.decode(detected, errors="strict"), detected, False
    except (UnicodeDecodeError, LookupError):
        pass
    try:
        return raw.decode(detected, errors="replace"), detected, True
    except LookupError:
        return raw.decode("utf-8", errors="replace"), "utf-8", True


def fix_cp1252_controls(text):
    result = []
    for c in text:
        code = ord(c)
        if 0x80 <= code <= 0x9F:
            try:
                result.append(bytes([code]).decode('cp1252'))
            except (ValueError, UnicodeDecodeError):
                result.append('')
        else:
            result.append(c)
    return ''.join(result)

def strip_diacritics(text):
    normalized = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')

LEADING_SPACES_RE = re.compile(r'^( +)')

def dedent_repeated_leading_spaces(text, min_lines=6):
    """Strip a leading-space run that recurs on many lines.

    Unicode "narrow" space variants (thin space, figure space, NBSP, etc.)
    each collapse to a single ASCII space earlier in the pipeline. Source
    files that stack several such characters per line (a common PDF/ebook
    extraction artifact used to fake kerning or a paragraph indent) end up
    with a tab-like run of real spaces on every line. A single stray indent
    is probably intentional; the same exact run repeated across many lines
    almost never is, so only prefixes that clear min_lines get removed.
    """
    lines = text.split('\n')
    prefixes = [
        m.group(1) if (m := LEADING_SPACES_RE.match(line)) else ''
        for line in lines
    ]
    counts = Counter(p for p, line in zip(prefixes, lines) if p and line.strip())
    to_strip = {p for p, c in counts.items() if c > min_lines}
    if not to_strip:
        return text, {}
    new_lines = [
        line[len(p):] if p in to_strip else line
        for line, p in zip(lines, prefixes)
    ]
    return '\n'.join(new_lines), {len(p): c for p, c in counts.items() if p in to_strip}

def repair_line_with_llm(line):
    prompt = (
        "The following line of text contains one or more Unicode replacement characters "
        "(U+FFFD) that stand in for corrupted or missing characters. "
        "Please repair the line by replacing the broken character(s) with whatever makes "
        "the most sense in context. Return only the repaired line, nothing else.\n\n"
        f"Line: {line}"
    )
    payload = {
        "model": "local-model",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    response = requests.post(LM_STUDIO_URL, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content'].strip()

def collect_txt_files(directory, recursive):
    if recursive:
        paths = []
        for dirpath, dirnames, filenames in os.walk(directory):
            # never descend into our own output buckets
            dirnames[:] = [d for d in dirnames if d not in ('clean', 'weird')]
            for name in filenames:
                if name.lower().endswith('.txt'):
                    paths.append(os.path.join(dirpath, name))
        return sorted(paths)
    return sorted(
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.lower().endswith('.txt')
    )

def main():
    parser = argparse.ArgumentParser(
        description="Clean .txt files to ASCII-ready UTF-8: detect encoding, "
                    "normalize newlines, replace non-ASCII characters, and route "
                    "each file into a clean/ or weird/ subfolder."
    )
    parser.add_argument('directory', nargs='?', default=None,
                        help="Folder with .txt files (prompted for if omitted)")
    parser.add_argument('-llm', action='store_true', help='Use LLM to repair U+FFFD replacement characters')
    parser.add_argument('-save', action='store_true', help='Route every file to clean/ even if weird characters remain')
    parser.add_argument('-force', action='store_true', help='Replace all remaining non-ASCII characters with a space')
    parser.add_argument('-r', '--recursive', action='store_true', help='Recurse into subdirectories')
    parser.add_argument('-no-dedent', action='store_true',
                        help='Disable stripping of repeated fake-indent leading spaces')
    parser.add_argument('-dedent-threshold', type=int, default=6, metavar='N',
                        help='Strip a leading-space run only if it recurs on more than N lines (default: 6)')
    args = parser.parse_args()

    directory = args.directory
    if not directory:
        directory = input("Enter directory: ")
    directory = directory.strip("'\"")
    print(f"Checking directory: {directory}")
    if not os.path.isdir(directory):
        print("Invalid directory")
        return

    txt_files = collect_txt_files(directory, args.recursive)

    # Replacements for non-standard quotes
    replacements = {
        '‘': "'",
        '’': "'",
        '“': '"',
        '”': '"',
        '—': '--',
        '–': '-',
        '…': '...',
        '•': '-',
        '©': ' ',
        '«': '"',
        '»': '"',
        '£': '$',
        '¯': '-',
        '°': '',
        '·': '.',
        '¤': '$',
        '„': '"',
        '￼': '',
        '‎': '',
        '﻿': '',
        ' ': ' ',
        '˝': '"',
        '‚': "'",
        '‹': "'",
        '­': '',
        '●': '-',
        '\x91': "'",
        '╝': '',
        '‡': '',
        '‟': '"',
        '❤': '',
        '☺': '',
        '¥': '$',
        '¬': '',
        '｣': "'",
        ' ': ' ',
        '¨': '',
        ' ': '\n',
        ' ': '\n\n',
        '⁄': '/',
        '‑': '-',
        ' ': ' ',
        '¢': '',
        '®': '',
        '×': '*',
        '´': "'",
        '​': '',
        '€': '$',
        '™': '',
        '☰': '',
        '″': '"',
        '╔': '',
        '˜': '',
        'ô': '"',
        'ö': '"',
        'Ē': '"',
        '›': "'",
        'Â': '',
        'ĺ': "'",
        'Ĺ': "'",
        'Æ': "'",
        'Ł': '$',
        'í': "'",
        'ó': '...',
        'É': '...',
        'Ň': '"',
        'Ó': '"',
        'Ő': "'",
        '¹': "'",
        'ů': '--',
        '½': '1/2',
        '¼': '1/4',
        '¾': '3/4',
        '÷': '/',
    }

    weird_dir = os.path.join(directory, 'weird')
    clean_dir = os.path.join(directory, 'clean')

    count_total = 0
    count_cleaned = 0
    count_weird = 0
    count_decode_errors = 0

    for filepath in txt_files:
        count_total += 1
        rel = os.path.relpath(filepath, directory)

        with open(filepath, 'rb') as f:
            raw = f.read()
        content, detected, used_replacement = decode_bytes(raw)
        if used_replacement:
            print(f"{rel}: decode errors under '{detected}' - substituted U+FFFD")
            count_decode_errors += 1

        original_content = content

        # Normalize newlines (replaces dos2unix): CRLF and lone CR -> LF
        content = content.replace('\r\n', '\n').replace('\r', '\n')

        # Decode C1 control characters as Windows-1252 before other processing
        content = fix_cp1252_controls(content)

        # Apply replacements for non-standard characters
        for old, new in replacements.items():
            content = content.replace(old, new)

        # Strip diacritics from remaining accented Latin characters (e→e, â→a, etc.)
        content = strip_diacritics(content)

        # LLM repair of U+FFFD replacement characters
        llm_repaired = False
        if args.llm and REPLACEMENT_CHAR in content:
            lines = content.split('\n')
            repaired_lines = []
            for line in lines:
                if REPLACEMENT_CHAR in line:
                    print(f"{rel}: Found unknown character (U+FFFD) in line: {line[:120]!r}")
                    try:
                        repaired = repair_line_with_llm(line)
                        print(f"{rel}: LLM repaired to: {repaired[:120]!r}")
                        repaired_lines.append(repaired)
                        llm_repaired = True
                    except Exception as e:
                        print(f"{rel}: LLM error - {e}")
                        repaired_lines.append(line)
                else:
                    repaired_lines.append(line)
            content = '\n'.join(repaired_lines)

        # Force-replace any remaining non-ASCII with a space
        if args.force:
            content = ''.join(c if ord(c) <= 127 else ' ' for c in content)

        # Strip fake-indent leading spaces (see dedent_repeated_leading_spaces)
        if not args.no_dedent:
            content, stripped = dedent_repeated_leading_spaces(content, args.dedent_threshold)
            for width, n in sorted(stripped.items()):
                print(f"{rel}: stripped {width}-space fake indent from {n} lines")

        # Check if content was modified
        modified = content != original_content

        weird_chars = set()
        weird_count = 0
        for char in content:
            if ord(char) > 127:
                weird_chars.add(char)
                weird_count += 1

        if weird_chars:
            print(f"\033[91m{rel}: {weird_count} unresolved characters\033[0m")
            for char in sorted(weird_chars, key=ord):
                print(f"  {repr(char)} (U+{ord(char):04X})")

        is_weird = weird_count > 0 and not args.save and not args.force
        dest = os.path.join(weird_dir if is_weird else clean_dir, rel)

        os.makedirs(os.path.dirname(dest), exist_ok=True)
        st = os.stat(filepath)
        with open(dest, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        os.utime(dest, (st.st_atime, st.st_mtime))  # keep original timestamps

        if is_weird:
            count_weird += 1
        else:
            if modified:
                print(f"{rel}: Cleaned and saved to clean/")
            count_cleaned += 1

    print(f"\nDone. {count_total} files scanned: {count_cleaned} to clean/, "
          f"{count_weird} to weird/, {count_decode_errors} had decode errors.")

if __name__ == "__main__":
    main()
