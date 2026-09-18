import textwrap


PAGE_WIDTH = 612
PAGE_HEIGHT = 792
LEFT_MARGIN = 72
TOP_Y = 720
BOTTOM_Y = 72
FONT_SIZE = 11
LINE_HEIGHT = 16


def _escape_pdf_text(value):
    return (
        value.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _wrap_letter(text):
    lines = []

    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue

        lines.extend(
            textwrap.wrap(
                paragraph.strip(),
                width=82,
                break_long_words=False,
                break_on_hyphens=False
            ) or [""]
        )

    return lines


def create_cover_letter_pdf(cover_letter):
    lines_per_page = int((TOP_Y - BOTTOM_Y) / LINE_HEIGHT)
    lines = _wrap_letter(cover_letter)
    pages = [
        lines[index:index + lines_per_page]
        for index in range(0, len(lines), lines_per_page)
    ] or [[""]]

    objects = []

    def add_object(value):
        objects.append(value)
        return len(objects)

    catalog_id = add_object("")
    pages_id = add_object("")
    font_id = add_object(
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    )
    page_ids = []

    for page_lines in pages:
        commands = [
            "BT",
            f"/F1 {FONT_SIZE} Tf",
            f"{LEFT_MARGIN} {TOP_Y} Td"
        ]

        for index, line in enumerate(page_lines):
            if index:
                commands.append(f"0 -{LINE_HEIGHT} Td")
            commands.append(f"({_escape_pdf_text(line)}) Tj")

        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", errors="replace")
        content_id = add_object(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
        page_id = add_object(
            "<< /Type /Page "
            f"/Parent {pages_id} 0 R "
            f"/MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        page_ids.append(page_id)

    objects[catalog_id - 1] = (
        f"<< /Type /Catalog /Pages {pages_id} 0 R >>"
    )
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id - 1] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>"
    )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]

    for object_id, value in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(
            value if isinstance(value, bytes) else value.encode("latin-1")
        )
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")

    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    output.extend(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            "startxref\n"
            f"{xref_offset}\n"
            "%%EOF\n"
        ).encode("ascii")
    )

    return bytes(output)
