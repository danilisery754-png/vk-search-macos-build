from app.services.normalization import extract_vk_community_refs


def test_extracts_dirty_vk_links_ids_and_deduplicates_preserving_order():
    raw = """
    текст (https://vk.com/example), ещё vk.ru/example и club123456;
    две в строке: https://vk.com/public777 https://vk.ru/club123456
    простой ID 987654 и мусор 123abc
    """

    refs = extract_vk_community_refs(raw)

    assert [item.lookup for item in refs] == ["example", "123456", "777", "987654"]
    assert refs[0].canonical_url == "https://vk.com/example"
    assert refs[1].canonical_url == "https://vk.com/club123456"
    assert refs[2].canonical_url == "https://vk.com/club777"


def test_ignores_profile_and_non_vk_urls_when_context_is_not_a_community_marker():
    refs = extract_vk_community_refs("https://example.com/club55 user123 test@example.com")
    assert refs == []

