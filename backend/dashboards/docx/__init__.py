"""Editable Word (.docx) report builders.

Parallel to `dashboards/pdf/`, these render the SAME report payloads +
LLM narrative as native, editable Word documents so the client can edit
the text and add comments. Charts are reused verbatim from the PDF chart
renderers (captured as PNGs via `charts._mpl.capture_docx_figures`);
data is rendered as native Word tables from the resolver payloads.
"""
