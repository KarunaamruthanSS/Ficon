import pytest

from offconv import registry
from offconv.registry import Options


def test_route_chains_converters():
    @registry.converter(["aaa"], ["bbb"])
    def a_to_b(src, dst, options): ...

    @registry.converter(["bbb"], ["ccc"])
    def b_to_c(src, dst, options): ...

    assert registry.find_route("aaa", "ccc") == [("aaa", "bbb"), ("bbb", "ccc")]
    assert registry.find_route("ccc", "aaa") is None


def test_registering_a_format_does_not_leak_between_tests():
    """The companion to the test above: 'aaa' must be gone again."""
    assert "aaa" not in registry.sources()
    assert registry.find_route("aaa", "ccc") is None


def test_same_format_is_not_a_route():
    assert registry.find_route("png", "png") is None


def test_real_registry_knows_image_formats():
    assert "png" in registry.sources()
    assert "pdf" in registry.targets_for("png")


@pytest.mark.parametrize("quality", [0, -1, 101, 1000])
def test_quality_outside_the_range_is_rejected(quality: int):
    with pytest.raises(ValueError, match="quality"):
        Options(quality=quality)


@pytest.mark.parametrize("size", [(0, 0), (-5, 10), (10, 0)])
def test_resize_must_be_positive(size):
    with pytest.raises(ValueError, match="resize"):
        Options(resize=size)


def test_negative_pixel_budget_is_rejected():
    with pytest.raises(ValueError, match="max_pixels"):
        Options(max_pixels=-1)


def test_sensible_options_are_accepted():
    assert Options(quality=80, resize=(100, 100), max_pixels=0).quality == 80
