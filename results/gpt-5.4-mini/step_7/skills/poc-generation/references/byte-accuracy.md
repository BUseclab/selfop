# Byte Accuracy

Use this when the PoC is binary, field-sensitive, or easy to corrupt through quoting, encoding, or packing mistakes.

## Rule

Do not validate a candidate until you have inspected the actual bytes on disk and confirmed they match the intended layout.

## What to check

- Endianness for multibyte fields.
- Field widths and signedness.
- Offsets, alignment, and padding.
- Length fields versus the real payload size.
- Escaping or quoting that may change the bytes written to disk.

## Workflow

1. Generate the candidate.
2. Inspect the bytes with a hex-level view.
3. Compare the on-disk layout against the intended structure.
4. Fix any packing or encoding mismatch before running the target.
5. Re-check the bytes after every edit that could change structure.

## Anti-patterns

- Do not assume a shell string equals the written file.
- Do not trust a generator result that has not been inspected at the byte level.
- Do not validate before confirming field order, byte order, and lengths.

## Useful question

Ask: "Do the actual bytes on disk match the structure the target will parse?"

