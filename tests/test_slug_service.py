from app.services.slug_service import make_product_slug, has_bad_placeholder_slug

def test_none_never_enters_slug():
    assert make_product_slug("6000 2RS", "KINEX", None) == "6000-2rs-kinex"

def test_generic_word_removed():
    assert make_product_slug("Підшипник 6205 2RS", "SKF", None) == "6205-2rs-skf"

def test_bad_slug_detection():
    assert has_bad_placeholder_slug("6000-2rs-kinex-none")
    assert not has_bad_placeholder_slug("6000-2rs-kinex")
