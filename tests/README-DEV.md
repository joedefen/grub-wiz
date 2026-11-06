# grub-wiz: working on the source tree

This is the developer companion to [`README.md`](../README.md), which documents
the tool for its users. Here we document the two things a maintainer needs and a
user does not: the **test gate** and the **release gate** (`./bless`).

This file lives in `tests/`, so its links point one directory up. The commands
assume the repository root, which is where the gate has to be run.

## Layout and single sources of truth

| Path | Owns |
| --- | --- |
| [`grub_wiz/__init__.py`](../grub_wiz/__init__.py) | `__version__`, and nothing else. The build backend reads it, `grub-wiz --version` prints it, `bless` reads the line without importing the package. |
| [`pyproject.toml`](../pyproject.toml) | Name, description, `requires-python`, runtime dependencies, the SPDX `license` and `license-files`, the `dev` extra, `[tool.bless]`, and the pytest, coverage and ruff configuration. |
| [`bless`](../bless) | The release gate, emitted verbatim from [`../../blessd/bless`](../../blessd/bless) by that repo's `build.py`. It holds no copy of this project's identity, and it is never edited here. |
| [`blessd/docs/release-strategy.md`](../../blessd/docs/release-strategy.md) | The release strategy every project shares: the branch model, the stages, the rehearsal, the credentials. This file documents only what is particular to `grub-wiz`. |
| [`tests/inspect_dist.py`](inspect_dist.py) | The distribution inspector. `bless` refuses to upload a wheel and sdist it has not inspected with this file; CI runs the same file. |
| [`tests/test_bless.py`](test_bless.py) | The identity this tree derives from `pyproject.toml` and the inspector it uploads behind. It deliberately does not test the gate's policy. |
| [`runner`](../runner) | Runs the tree from source (`python -m grub_wiz.main`) for debugging. |
| [`.gitignore`](../.gitignore) | Keeps gate artifacts (`build/`, `dist/`, `.coverage*`, caches, `*.whl`, `*.tar.gz`) out of `git status`, because the gate refuses a dirty tree. |

The version lives in exactly one place. `pyproject.toml` declares
`dynamic = ["version"]`, so flit reads `grub_wiz/__init__.py`; a
`X.Y.Z.99.N` rehearsal rewrites that line only inside a throwaway copy. A second
copy of the version in `[project]` is how published metadata drifts away from
the code, so it is not there.

`grub-wiz --version` is answered before the `sudo` re-exec
([`main()`](../grub_wiz/main.py:2957)), because the smoke stage of the release
gate runs it as an ordinary user on a machine with no saved state. `--help` is
answered there too, for the same reason.

## The test gate

Install what the gate needs (this is the interpreter that must run `bless`,
too):

    python3 -m venv .venv
    .venv/bin/python -m pip install -e '.[dev]'

`bless` runs every stage with `sys.executable`, so it has to be *that*
interpreter -- the one holding `console-window` and the dev extra. Activate the
virtualenv first, or start the gate by hand:

    .venv/bin/python ./bless

Then the commands `bless` runs, in the same order, on the same interpreter:

    python -m ruff check .
    python -m compileall -q grub_wiz tests
    python -m pytest -q --cov=grub_wiz --cov-report=term-missing

CI runs the same three commands, not equivalents, so a green gate means the
same thing in both places. The coverage floor (60%) is enforced through
`[tool.coverage.report] fail_under`; it was set just below the measured number
when the gate was adopted. Raise it when the number rises, never lower it.

The ruff selection is committed rather than inherited
(`[tool.ruff.lint] select = ["E4", "E7", "E9", "F"]`, `target-version = "py310"`)
so that no user or global configuration can change what the gate enforces.

## The release gate: `./bless`

`./bless` takes no arguments and has no flag that skips a stage. It always runs
everything, then prints what it has in hand and asks one question:

    ====> Enter test or publish or quit:

Only `test` and `publish` are accepted, spelled in full; anything else is asked
again. Enter, `quit` or Ctrl-C stops with nothing tagged, uploaded or pushed.

`./bless --branch-plan` is the one exception, and it does not enter the gate: it
prints this tree's branch plan as JSON and exits, which is how `bt` asks the
same question the release will answer.

**Stages, in order**

1. **preflight** -- clean tree, the `vX.Y.Z` tag absent, `twine>=7` and
   `packaging>=26` present, `python -m build` available.
2. **index check** -- refuses if `__version__` is already on PyPI, printing
   every published version, before anything is built or uploaded.
3. **gates** -- the three commands above.
4. **build** -- into `build/bless-<version>/`, wiped first, so no older
   artifact can be sent by mistake.
5. **inspect** -- `tests/inspect_dist.py` against the wheel and the sdist.
6. **check** -- `twine check --strict` on both files.
7. **smoke** -- installs the built wheel into a throwaway venv and runs
   `grub-wiz --version`, which must print the version being released.
8. **branch plan** -- refuses a detached HEAD, a branch that is not one of the
   release branches, a release branch missing locally or on origin, two
   branches that have diverged, or a push that would not fast-forward.

**`test`** is the rehearsal and never spends the working version. It copies the
tree to `build/bless-test-<version>/src`, rewrites `__version__` to
`X.Y.Z.99.N` (99 keeps it clear of real releases; `N` is one past the highest
suffix TestPyPI already holds for that base), builds, inspects and smoke-tests
the copy, and uploads only to `test.pypi.org`. No tag, no branch, no push. It
prints the install line, which needs `python -m pip cache purge` first and
`--extra-index-url https://pypi.org/simple/`, because TestPyPI carries no
dependencies.

**`publish`** fast-forwards the release branches to one commit, tags `vX.Y.Z`,
uploads the two inspected files to PyPI, verifies the index, and pushes those
branches and the tag.

**Credentials** are resolved per index -- `TWINE_PASSWORD` for PyPI,
`TWINE_TESTPYPI_PASSWORD` for TestPyPI, each overruling the `~/.pypirc` section
whose `repository` matches that index's upload URL -- so a PyPI token is never
spent on a rehearsal. A missing credential is a refusal before `twine` starts.

**Verification** reads the index back after an upload. The read is cache-busted
and patient (up to a quarter of an hour), because both indexes list new releases
through a CDN that lags; a release that is not listed yet is reported as lag
with the project page to check, never as a failed upload, since an accepted
upload cannot be withdrawn.

There is no CI publish job, on purpose: the upload is irreversible and is run by
the owner from the development tree, so the safety lives in one inspectable
command. CI stays a gate.

## The branch model is a setting, not a convention

`bless` publishes only from a branch it was told about, and pushes every branch
it was told about. Which ones those are is `[tool.bless] branches` in
[`pyproject.toml`](../pyproject.toml), and there are two shapes:

* `branches = ["main"]` -- one release branch. Nothing is aligned, and `publish`
  pushes `main` and the tag.
* `branches = ["main", "dev"]` -- the default when the setting is absent. While
  you are on `main`, `dev` does not have to exist yet: the trunk alone satisfies
  the model, so `publish` releases from `main` and pushes only what exists. Once
  `dev` has been created it also has to exist as `origin/dev`, and whichever of
  the two lags is fast-forwarded onto the other before the tag, so a release
  always leaves them at one commit.

This project declares `["main", "dev"]`; both branches exist locally and on
origin, so a release leaves them at one commit and tags that commit.

Either way the gate refuses a branch it was not told about, a branch it has to
push that is missing on origin, two branches that have diverged, and a push that
would not fast-forward. What a single branch cannot do is notice that a
development branch was left behind: merging `dev` into `main` stays the
maintainer's job, and the pair exists to make it the gate's job instead.

## What the inspector asserts

[`tests/inspect_dist.py`](inspect_dist.py) is the one implementation, used by
`bless` and by CI; expectations are read from `pyproject.toml` and the package,
never from the artifact under test.

* **wheel** -- `Name`, `Version`, `Summary`, `Requires-Python`, `Keywords`,
  `License-Expression` and the *runtime* `Requires-Dist` names match
  `pyproject.toml`; every declared `license-files` entry is listed in
  `License-File`; every `grub_wiz/*.py` and `grub_wiz/canned_config.yaml` is
  present; a `LICENSE` is carried; no `tests/`, no `.venv`, no `__pycache__`,
  no `.pyc`.
* **sdist** -- carries `pyproject.toml`, `README.md`, `LICENSE`,
  `grub_wiz/__init__.py`, `grub_wiz/main.py` and
  `grub_wiz/canned_config.yaml`; the `__version__` inside the sdist equals the
  artifact version; no venv or bytecode. The sdist is deliberately lean: flit's
  default payload is enough and `tests/` need not ride along.

Run it by hand on any built pair:

    python tests/inspect_dist.py dist/grub_wiz-2.0.1-py3-none-any.whl \
                                dist/grub_wiz-2.0.1.tar.gz

## Releasing, in three steps

1. Bump `__version__` in [`grub_wiz/__init__.py`](../grub_wiz/__init__.py) and
   commit.
2. Run `./bless`. The gate runs in full.
3. Answer `test` to rehearse on TestPyPI, then run `./bless` again and answer
   `publish` -- or go straight to `publish`.

`[tool.bless] branches` names what `publish` pushes. Both branches in that list
must exist and track origin; `publish` leaves them at the tagged commit.
Everything else about the release is one of the stages above, and the shared
half lives in [`blessd/docs/release-strategy.md`](../../blessd/docs/release-strategy.md).

## Notes on this adoption

* This section is one run of
  [`../../blessd/docs/adopting.md`](../../blessd/docs/adopting.md), which is the
  procedure written for whoever converts the next project. If the two ever
  disagree, that document is the procedure and this is the record of one run.
* [`bless`](../bless) is emitted, byte for byte, from
  [`../../blessd/bless`](../../blessd/bless) -- SHA-256
  `3ef60e9e806ca58a3d900dd6622bb8be0052210da1ef26f9918bf0a1deb1e3b2` when this
  was written (55,222 bytes). It is not edited here: a change is made in
  `blessd` and re-emitted with
  `python3 ../blessd/build.py --into . --force`, which replaces the file and
  prints the new hash.
* `grub-wiz` needed five things: one version location
  (`dynamic = ["version"]` and `__version__` in `grub_wiz/__init__.py`), an
  inspector, the `dev` extra with `pytest-cov`, `build`, `twine>=7`,
  `packaging>=26` and a `tomli` fallback for Python 3.10, a console script that
  answers `--version` before the `sudo` re-exec, and a branch model for the
  branch plan -- here `branches = ["main", "dev"]`.
* The project had no `tests/test_bless.py` before adoption, so there were no
  tests of the gate's policy to delete. The file now present pins only this
  tree's identity and the inspector; the gate itself -- branch plan, refusals,
  prompt, index check, emitter -- is tested once, in
  [`../../blessd/tests/test_bless.py`](../../blessd/tests/test_bless.py).
* `bt` reads the branch plan through `./bless --branch-plan`; `bt audit` is the
  outside check that this project's `bless` is the build named above, and
  `bt status` prints the same answer as one non-blocking line.
