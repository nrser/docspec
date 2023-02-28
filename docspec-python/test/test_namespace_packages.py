from functools import reduce
from pathlib import Path, PurePath
import pytest
import typing as t

from docspec_python.namespace_packages import (
    RelPathPattern,
    root_reducer,
)


def is_match(
    pattern: str, path: t.Union[Path, str], *, rel_to: t.Optional[Path] = None
):
    assert RelPathPattern(pattern).is_match(Path(path), rel_to=rel_to) is True


def is_not_match(
    pattern: str, path: t.Union[Path, str], *, rel_to: t.Optional[Path] = None
):
    assert RelPathPattern(pattern).is_match(Path(path), rel_to=rel_to) is False


def test_free_patterns():
    is_match("test", "test/a/b")
    is_match("test", "a/test/b")
    is_match("test", "a/b/test")


def test_anchored_patterns():
    is_match("/test", "test/a/b")
    is_not_match("/test", "a/test/b")
    is_not_match("/test", "a/b/test")

    is_match("test/a", "test/a/b")
    is_not_match("test/a", "b/test/a")


def test_double_splat_patterns():
    is_match("**/test/b", "a/test/b/c")

    is_match("test/**/c", "test/a/b/c/d")
    is_match("test/**/c", "test/c")
    is_not_match("test/**/c", "a/test/c")


def test_negate_patterns():
    is_match("!test", "a/b/c")
    is_not_match("!test", "a/test/b/c")


def test_slash_bang_patterns():
    is_match("\\!test", "a/!test/b")


def test_fnmatch_patterns():
    is_match("*/a/b", "x/a/b/c")
    is_not_match("*/a/b", "a/b/c")
    is_not_match("*/a/b", "x/y/a/b/c")


def test_dir_only_patterns(tmp_path: Path):
    file_rel_path = Path("test/file")
    dir_rel_path = Path("test/dir")

    (tmp_path / file_rel_path).parent.mkdir(parents=True)
    (tmp_path / file_rel_path).touch()

    is_match("test/file", file_rel_path, rel_to=tmp_path)
    is_not_match("test/file/", file_rel_path, rel_to=tmp_path)

    (tmp_path / dir_rel_path).mkdir(parents=True)

    is_match("test/dir", dir_rel_path, rel_to=tmp_path)
    is_match("test/dir/", dir_rel_path, rel_to=tmp_path)

    is_match("/test/", file_rel_path, rel_to=tmp_path)


def test_bad_patterns():
    for pattern in ["", "/", "///", "!"]:
        with pytest.raises(ValueError):
            RelPathPattern(pattern)


def test_bad_paths():
    for path in ["/a/b/c", "/", "//"]:
        with pytest.raises(ValueError):
            RelPathPattern("test").is_match(PurePath(path))


def is_descentent_of(path: Path, other: Path) -> bool:
    return other in path.parents

def reduces_to(input: list[str], output: list[str]):
    assert reduce(
        root_reducer(is_descentent_of),
        (Path(p) for p in input),
        [],
    ) == [Path(p) for p in output]


def test_root_reducer():
    reduces_to(
        [
            "a",
            "a/b",
            "a/b/c",
            "a/b/d",
        ],
        ["a"],
    )

    reduces_to([
        "a/b",
        "a/b/c",
        "a/b/d/e",
        "x/y",
        "x/y/z",
        "x/y/w",
    ], ["a/b", "x/y"])
