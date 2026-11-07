from ledgerkit.money import split


def test_even_split():
    assert split(100, [1, 1]) == [50, 50]
