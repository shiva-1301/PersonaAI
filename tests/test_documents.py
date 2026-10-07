import io

import pytest

from core.documents import (
    DocumentError, Page, _looks_word_per_line, _strip_repeated_lines, chunk_pages, extract_pages,
)


def words(n, start=0):
    return " ".join(f"w{i}" for i in range(start, start + n))


def test_short_page_is_one_chunk():
    chunks = chunk_pages([Page(3, words(100))])
    assert len(chunks) == 1
    assert chunks[0].page == 3


def test_long_page_splits_with_overlap_and_keeps_page():
    chunks = chunk_pages([Page(1, words(400))], size=180, overlap=40)
    assert [len(c.text.split()) for c in chunks] == [180, 180, 120]
    # 40-word overlap between neighbours
    assert chunks[0].text.split()[-40:] == chunks[1].text.split()[:40]
    assert all(c.page == 1 for c in chunks)
    assert [c.index for c in chunks] == [0, 1, 2]


def test_tiny_tail_is_merged_not_its_own_chunk():
    chunks = chunk_pages([Page(1, words(190))], size=180, overlap=40)
    assert len(chunks) == 1 and len(chunks[0].text.split()) == 190


def test_chunks_never_span_pages():
    chunks = chunk_pages([Page(1, words(50)), Page(2, words(50, 50))])
    assert [c.page for c in chunks] == [1, 2]


def test_header_lines_removed_but_repeated_body_labels_kept():
    pages = [f"Prepared by K. Lecturer Page {i}\nTopic {i}\nAnswer:\nbody {i}\nAnswer:\nend {i}"
             for i in range(1, 6)]
    cleaned = _strip_repeated_lines(pages, edge=1)
    assert all("Prepared by" not in p for p in cleaned)
    assert all(p.count("Answer:") == 2 for p in cleaned)


def test_word_per_line_detection():
    assert _looks_word_per_line("\n \n".join(["word"] * 40))
    assert not _looks_word_per_line("\n".join(["a normal line of text here"] * 40))


def test_txt_and_docx_extraction():
    pages = extract_pages("notes.txt", b"Hive is a data warehouse.\n\nPig is a dataflow language.")
    assert pages[0].number is None and "Hive" in pages[0].text

    import docx
    d = docx.Document()
    d.add_paragraph("Sqoop imports data from RDBMS.")
    buf = io.BytesIO(); d.save(buf)
    assert "Sqoop" in extract_pages("n.docx", buf.getvalue())[0].text


@pytest.mark.parametrize("name,data", [("a.pptx", b"x"), ("a.txt", b""), ("a.txt", b"  \n ")])
def test_bad_files_rejected(name, data):
    with pytest.raises(DocumentError):
        extract_pages(name, data)
