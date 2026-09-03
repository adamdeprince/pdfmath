"""Shared fixtures.  Compilation is expensive, so corpora are built once per session."""

from __future__ import annotations

import pytest

from pdfmath.corpus.compile import have_pdflatex

requires_tex = pytest.mark.skipif(not have_pdflatex(),
                                  reason="pdflatex is not installed")


@pytest.fixture(scope="session")
def workdir(tmp_path_factory) -> str:
    return str(tmp_path_factory.mktemp("corpus"))


@pytest.fixture(scope="session")
def compiled(workdir):
    """Compile one expression and return (extract, tree, ctx) for it."""
    from pdfmath.corpus.compile import compile_expressions
    from pdfmath.extraction.pdfminer_backend import extract_page
    from pdfmath.parse.driver import parse_page

    def build(tex: str, page: int = 1):
        c = compile_expressions([tex], workdir=workdir)
        extract = extract_page(c.pdf_path, page)
        tree, ctx = parse_page(extract)
        return extract, tree, ctx

    return build
