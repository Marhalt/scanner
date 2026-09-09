import os
import string
import argparse
import unicodedata
import requests

REPLACEMENT_CHAR = '�'
LM_STUDIO_URL = 'http://localhost:1234/v1/chat/completions'

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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', nargs='?', default=None)
    parser.add_argument('-llm', action='store_true', help='Use LLM to repair U+FFFD replacement characters')
    parser.add_argument('-save', action='store_true', help='Save all modified files in place, skip weird/ routing')
    parser.add_argument('-force', action='store_true', help='Replace all remaining non-ASCII characters with a space')
    args = parser.parse_args()

    directory = args.directory
    if not directory:
        directory = input("Enter directory: ")
    directory = directory.strip("'\"")
    print(f"Checking directory: {directory}")
    if not os.path.isdir(directory):
        print("Invalid directory")
        return

    txt_files = [f for f in os.listdir(directory) if f.endswith('.txt')]

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
    count_unreadable = 0

    for filename in txt_files:
        count_total += 1
        filepath = os.path.join(directory, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(filepath, 'r', encoding='latin-1') as f:
                    content = f.read()
            except UnicodeDecodeError:
                print(f"{filename}: Could not decode")
                count_unreadable += 1
                continue

        # Decode C1 control characters as Windows-1252 before other processing
        original_content = content
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
                    print(f"{filename}: Found unknown character (U+FFFD) in line: {line[:120]!r}")
                    try:
                        repaired = repair_line_with_llm(line)
                        print(f"{filename}: LLM repaired to: {repaired[:120]!r}")
                        repaired_lines.append(repaired)
                        llm_repaired = True
                    except Exception as e:
                        print(f"{filename}: LLM error - {e}")
                        repaired_lines.append(line)
                else:
                    repaired_lines.append(line)
            content = '\n'.join(repaired_lines)

        # Force-replace any remaining non-ASCII with a space
        if args.force:
            content = ''.join(c if ord(c) <= 127 else ' ' for c in content)

        # Check if content was modified
        modified = content != original_content

        weird_chars = set()
        weird_count = 0
        for char in content:
            if ord(char) > 127:
                weird_chars.add(char)
                weird_count += 1

        if weird_chars:
            print(f"\033[91m{filename}: {weird_count} unresolved characters\033[0m")
            for char in sorted(weird_chars, key=ord):
                print(f"  {repr(char)} (U+{ord(char):04X})")

        if weird_count > 0 and not args.save and not args.force:
            os.makedirs(weird_dir, exist_ok=True)
            with open(os.path.join(weird_dir, filename), 'w', encoding='utf-8') as f:
                f.write(content)
            count_weird += 1
        else:
            os.makedirs(clean_dir, exist_ok=True)
            with open(os.path.join(clean_dir, filename), 'w', encoding='utf-8') as f:
                f.write(content)
            if modified:
                print(f"{filename}: Cleaned and saved to clean/")
            count_cleaned += 1

    print(f"\nDone. {count_total} files scanned: {count_cleaned} cleaned, {count_weird} moved to weird/, {count_unreadable} unreadable.")

if __name__ == "__main__":
    main()
