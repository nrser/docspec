# NOTE  (@nrser) VSCode and Python File Formatting
#
#       I'm using VSCode -- which I would guess the project author is
#       as well as `/.vscode` is ignored in the root `.gitignore` -- and I'm
#       pretty accustom to auto-formatting source files at this point.
#
#       I'm not sure which formatter @NiklasRosenstein is using, or if he is at
#       all, but it can't be `black`` (which I normally use) because it does not
#       allow for the obvious 2-space indent style. So I tried out the default
#       `autopep8` with 2-space indent and 120 character line limit and it seems
#       decently close.
#
#       As `/.vscode` is ignored, you'll have to add `.vscode/settings.json`
#       locally for each working directory. Right now mine look like:
#
#       ```jsonc
#       {
#         "[python]": {
#           "editor.formatOnSave": false,
#           "editor.tabSize": 2
#         },
#         "python.analysis.typeCheckingMode": "basic",
#         "python.analysis.importFormat": "relative",
#         "python.formatting.provider": "autopep8",
#         "python.formatting.autopep8Args": [
#           "--max-line-length", "120",
#           "--indent-size", "2",
#         ],
#       }
#       ```
#

from __future__ import annotations
from fnmatch import fnmatch
from functools import reduce
import os
import textwrap
import typing as t
from dataclasses import dataclass
from pathlib import Path, PurePath


T = t.TypeVar("T")
TRelPathPattern = t.TypeVar("TRelPathPattern", bound="RelPathPattern")


#: Default pattern to exclude when finding packages. This becomes important
#: when you have a `.venv` directory adjacent to the package directory;
#: otherwise we'll pick up all the dependency packages.
#:
#: This list is largely adapted from [gitignore/Python.gitignore][].
#:
#: As the calls to `docspec_python.discover` are relatively "deep" in the call
#: chains, at the moment the recommendation for customizing exclude behavior
#: is just to modify this list directly, which you can do from your
#: `novella.build` file with something like:
#:
#:    from docspec_python.namespace_packages import EXCLUDE_PATTERNS
#:
#:    do
#:      name: "configure"
#:      closure: {
#:        precedes "copy-files"
#:      }
#:      action: {
#:        EXCLUDE_PATTERNS.extend(["/example/", "/dev/"])
#:      }
#:
#: [gitignore/Python.gitignore]: https://github.com/github/gitignore/blob/main/Python.gitignore
#:
EXCLUDE_PATTERNS = [
    # Byte-compiled / optimized / DLL files
    "__pycache__/",
    # Distribution / packaging
    "/build/",
    "/develop-eggs/",
    "/dist/",
    "/downloads/",
    "/eggs/",
    "/.eggs/",
    "/lib/",
    "/lib64/",
    "/parts/",
    "/sdist/",
    "/var/",
    "/wheels/",
    "/pip-wheel-metadata/",
    "/share/python-wheels/",
    "/*.egg-info/",
    # Environments
    ".env/",
    ".venv/",
    "env/",
    "venv/",
    "ENV/",
    "env.bak/",
    "venv.bak/",
    # Editors
    ".vscode/",
    "/docs/",
    "/test/",
    "/tests/",
]


class RelPathPattern:
  """A small (~200 lines) patten matcher for _relative_ file paths modeled off
  the [Git Ignore][] pattern format.

  It operates by splitting the pattern into _terms_ by the '/' separator, and
  matching individual _terms_ against entries from `pathlib.Path.parts` using
  `fnmatch.fnmatch`. '**' terms are supported, which essentially allow the
  matching logic to "scan" through the path parts for the next match (greedy).

  This implementation makes _no_ guarantees of adhereing to the Git Ignore
  syntax, but it does make a reasonable attempt.

  Hopefully it _is_ sufficient to specify basic path exclusion rules as
  necessary for discovering packages when [native namespace packages][] are
  taken into account, particularly when combined with "[flat-layout][]" and
  Poetry's [virtualenvs.in-project][] option.

  Examples can be found at `test/test_namespace_packages.py`.

  [Git Ignore]: https://git-scm.com/docs/gitignore#_pattern_format
  [native namespace packages]: https://packaging.python.org/en/latest/guides/packaging-namespace-packages/#native-namespace-packages
  [flat-layout]: https://setuptools.pypa.io/en/latest/userguide/package_discovery.html#flat-layout
  [virtualenvs.in-project]: https://python-poetry.org/docs/configuration/#virtualenvsin-project
  """

  @classmethod
  def of(
      cls: type[TRelPathPattern], value: t.Union[str, TRelPathPattern]
  ) -> RelPathPattern:
    if isinstance(value, cls):
      return value
    if isinstance(value, str):
      return cls(value)
    raise TypeError(
        "expected {} or str, given {}: {!r}".format(
            cls.__name__, type(value), value
        )
    )

  pattern: str
  terms: tuple[str, ...]
  anchored: bool = False
  negate: bool = False
  dir_only: bool = False

  def __init__(self, pattern: str):
    self.pattern = pattern

    # '!' prefix negates the pattern
    if pattern.startswith("!"):
      self.negate = True
      pattern = pattern[1:]

    elif pattern.startswith("\\!"):
      # '\!' becomes literal '!'
      pattern = pattern[1:]

    # '/' on the end means only match directories
    if pattern.endswith("/"):
      self.dir_only = True
      pattern = pattern.rstrip("/")

    # patterns that otherwise contain '/' are "anchored" to only match at the
    # start of the relative path
    if "/" in pattern:
      self.anchored = True

    # Split by '/', dropping empty terms
    terms = tuple(term for term in pattern.split("/") if term)

    # We require terms; if parsing a file with empty lines and comments those
    # should be filtered out before construction
    if not terms:
      raise ValueError(
          f"must provide pattern with terms; given {self.pattern!r}"
      )

    self.terms = terms

  def __repr__(self) -> str:
    return f"{self.__class__.__name__}({self.pattern!r})"

  def _is_match(
      self,
      rel_path: PurePath,
      anchored: bool,
      rel_to: t.Optional[Path] = None,
      term_index: int = 0,
      part_index: int = 0,
  ) -> bool:
    # If we successfully matched all the terms then the pattern matches
    if term_index >= len(self.terms):
      # Conditional to the path it finished matching at being a directory,
      # if `dir_only` is true and we're been passed a `rel_to` base path
      # (otherwise we don't know where it is to check)
      if self.dir_only and rel_to is not None:
        return Path(rel_to, *rel_path.parts[:part_index]).is_dir()

      return True

    # If we ran out of path parts before matching all the terms then it's not a
    # match
    if part_index >= len(rel_path.parts):
      return False

    file_pattern = self.terms[term_index]

    # If we hit a '**' that means we can "un-anchor" and scan through the path
    # parts until we match the next term
    if file_pattern == "**":
      # Turn anchoring off and advance the term index
      return self._is_match(
          rel_path=rel_path,
          anchored=False,
          rel_to=rel_to,
          term_index=term_index + 1,
          part_index=part_index,
      )

    # See if the current path part matches the current file pattern
    if fnmatch(rel_path.parts[part_index], file_pattern):
      # If so, we're still matching; advance in both sequences
      return self._is_match(
          rel_path=rel_path,
          anchored=True,
          rel_to=rel_to,
          term_index=term_index + 1,
          part_index=part_index + 1,
      )

    # If we didn't match the part/pattern combo, and we are "anchored", then the
    # match fails (because we can't just go on to the next path part)
    if anchored:
      return False

    # Go on to the next path part by advancing that index
    return self._is_match(
        rel_path=rel_path,
        anchored=False,
        rel_to=rel_to,
        term_index=term_index,
        part_index=part_index + 1,
    )

  def is_match(
      self,
      rel_path: PurePath,
      *,
      rel_to: t.Optional[Path] = None,
  ) -> bool:
    if rel_path.is_absolute():
      raise ValueError(f"only matches relative paths; given {rel_path}")

    result = self._is_match(
        rel_path=rel_path,
        anchored=self.anchored,
        rel_to=rel_to,
    )

    return (not result) if self.negate else result


@dataclass
class FoundModule:
  """ """

  #: The full, absolute path to the module
  path: Path

  #: The relative path it was found at
  rel_path: Path

  #: The direcotry that was searched (what `rel_path` is relative to),
  # _exactly_ as it was handed to `find_module_roots` (because I _think_ it
  #: matter sometimes? Like `../src/` versus the absolute path to there).
  search_dir: t.Union[Path, str]

  @property
  def name(self) -> str:
    """Import (module) name."""
    return ".".join(self.rel_path.with_suffix("").parts)

  @property
  def is_package_dir(self) -> bool:
    return self.path.is_dir()

  @property
  def is_module_file(self) -> bool:
    return self.path.is_file()

  @property
  def search_path(self) -> str:
    return os.path.join(self.search_dir, self.rel_path)

  def is_descendant_of(self, other: FoundModule) -> bool:
    return other.path in self.path.parents

  def __repr__(self) -> str:
    return textwrap.dedent(
        f"""
      {self.__class__.__name__}(
          name            = {self.name!r}
          path            = {self.path!r}
          rel_path        = {self.rel_path!r}
          search_dir      = {self.search_dir!r}
          search_path     = {self.search_path!r}
          is_package_dir  = {self.is_package_dir!r}
          is_module_file  = {self.is_module_file!r}
      )
      """
    )


def root_reducer(
    is_descendant: t.Callable[[T, T], bool]
) -> t.Callable[[list[T], T], list[T]]:
  def reducer(roots: list[T], item: T) -> list[T]:
    to_rm = []

    for root in roots:
      if is_descendant(item, root):
        return roots
      if is_descendant(root, item):
        to_rm.append(root)

    for root in to_rm:
      roots.remove(root)

    roots.append(item)

    return roots

  return reducer


#: Special `__init__.py` contents denoting a `pkgutil` or `pkg_resource`-style
#: namespace.
NAMESPACE_INIT_CONTENTS = frozenset(
    {
        "__path__ = __import__('pkgutil').extend_path(__path__, __name__)",
        "__import__('pkg_resources').declare_namespace(__name__)",
        textwrap.dedent(
            """
            try:
                __import__('pkg_resources').declare_namespace(__name__)
            except ImportError:
                __path__ = __import__('pkgutil').extend_path(__path__, __name__)
            """
        ),
    }
)


def is_namespace_init(path: Path) -> bool:
  """Is this an init file for a `pkgutil` or `pkg_resources`-style namespace?

  See https://packaging.python.org/en/latest/guides/packaging-namespace-packages/
  """
  return (
      path.name == "__init__.py"
      and path.read_text().strip() in NAMESPACE_INIT_CONTENTS
  )


def find_module_roots(
    search_dir: t.Union[str, Path],
    exclude: t.Iterable[str] = EXCLUDE_PATTERNS,
) -> list[FoundModule]:
  """
  Find descdentant paths of `search_dir` that should be discovered as modules
  and packages, taking [PEP 420 – Implicit Namespace Packages][PEP 420] into
  account.

  If `search_dir` does not exist no results are generated. If `search_dir` does
  exists but is not a directory an `AssertionError` is raised.

  [PEP 420]: https://peps.python.org/pep-0420/

  In a technical sense, find all directories `D` such that:

  1.  `D` is a directory that a descendant of `search_dir` (subdirectory,
      subdirectory of subdirectory, ...) .
  2.  File `D/__init__.py` exists.
  3.  No ancestor (parent, parent of parent, ...) directories of `D` satisfy
      (1) and (2).

  This implementation takes [native namespace packages][] into account, where,
  relative to the `search_dir` you may have a structure like

      mynamespace/
          subpackage_a/
              __init__.py

  [native namespace packages]: https://packaging.python.org/en/latest/guides/packaging-namespace-packages/#native-namespace-packages

  It seems possible to add additional namespace layers as well, so the "root
  init" file (`__init__.py` in the above example) _may reside arbitrarily deep_
  in the subdirectory structure.

  This changes the problem from looking for `<name>/__init__.py` to looking
  for `<name_0>/<name_1>/.../<name_n>/__init__.py`, which is considerably more
  complex, as globbing `**/__init__.py` will find _all_ the init files in the
  package, which must be sorted through to find the "root" one.

  ##### Parameters #####

  -   `search_dir` -- directory to search under.
  -   `exclude` -- Path patterns to exclude. Basically `.gitgnore`-style, see
      `EXCLUDE_PATTERNS` for examples and `RelPathPattern` for details.

  ##### Returns #####

  The found directories as `list` of structures, each having

  -   `name: str` -- Import name of the package (such as
      `mynamespace.subpackage_a`)
  -   `rel_path: pathlib.Path` -- Relative path to the directory from
      `search_dir`.

  as well as some other things, check out `FoundModule` if you care to.

  """
  search_path = Path(search_dir)

  if not search_path.exists():
    return []

  # We need to work with the absolute path so `Path.relative_to` works
  search_abs_path = Path(search_dir).resolve()

  exclude_patterns = [RelPathPattern.of(item) for item in exclude]

  def is_excluded(path: Path) -> bool:
    rel_path = path.relative_to(search_abs_path)
    for pattern in exclude_patterns:
      if pattern.is_match(rel_path, rel_to=search_abs_path):
        return True
    return False

  # Make sure we have a directory
  assert (
      search_abs_path.is_dir()
  ), f"`search_dir` must be a directory, given {search_dir}"

  # First, collect all the modules we can find, both those that are a package
  # and those that are just a plain module-file.
  found_modules: list[FoundModule] = []

  # Go over all the `.py` paths that are descendants of `search_dir`
  for path in search_abs_path.glob("**/*.py"):
    rel_path = path.relative_to(search_abs_path)

    # Filter things out we dont' want...

    # If must be a file (no directories)
    if not path.is_file():
      continue

    # Relative path can not just be "__init__.py" because we would have no
    # name to import it as
    if rel_path.parts == ("__init__.py",):
      continue

    # All the directories in the relative path must not have '.' in them
    if any("." in part for part in rel_path.parent.parts):
      continue

    # It can not be a namespace init ("pkgutil-style" or "pkgresources-
    # style" namespace package, which is tested via inspecting the file
    # contents)
    if is_namespace_init(path):
      continue

    # It can not be excluded by the patterns
    if is_excluded(path):
      continue

    # We use the containing directory in the case of `.../__init__.py` to
    # make the subsequent reduction to root work. We know there is a parent
    # directory on the `rel_path` because we already tossed plain
    # `__init__.py` above
    if path.name == "__init__.py":
      path = path.parent
      rel_path = rel_path.parent

    found_modules.append(
        FoundModule(
            path=path,
            rel_path=rel_path,
            search_dir=search_dir,
        )
    )

  # Reduce that list so that it contains no "related" paths -- paths that are
  # ancestors or descendants of other paths in the list -- and that's it!
  return reduce(root_reducer(FoundModule.is_descendant_of), found_modules, [])
