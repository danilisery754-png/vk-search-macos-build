from io import BytesIO

from openpyxl import load_workbook

from app.services.exporting import ResultExportRow, links_text, rows_tsv, rows_xlsx


ROWS = [
    ResultExportRow("Паблик 1", "https://vk.com/pub1", "Отправлено", "Не отправлено", "ЛС", "Основной", ""),
    ResultExportRow("Паблик 2", "https://vk.com/pub2", "Не отправлено", "Отправлено", "Предложка", "Покупка №3", ""),
]


def test_links_are_clean_one_per_line():
    assert links_text(ROWS) == "https://vk.com/pub1\nhttps://vk.com/pub2"


def test_tsv_has_headers_and_separate_columns():
    text = rows_tsv(ROWS)
    lines = text.splitlines()
    assert lines[0].split("\t") == ["Группа", "Ссылка", "ЛС", "Предложка", "Куда получилось", "Аккаунт", "Причина"]
    assert lines[1].split("\t")[1] == "https://vk.com/pub1"
    assert len(lines) == 3


def test_xlsx_opens_and_contains_links_in_separate_rows():
    workbook = load_workbook(BytesIO(rows_xlsx(ROWS)))
    sheet = workbook.active
    assert sheet["A1"].value == "Группа"
    assert sheet["B2"].value == "https://vk.com/pub1"
    assert sheet["B3"].value == "https://vk.com/pub2"
