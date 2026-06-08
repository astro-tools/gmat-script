"""The text-edit mechanism the mutation API splices with — byte-range edits, never node surgery.

An edit is a byte-range replacement into the source (a :class:`_Edit`); applying a batch of them
(:func:`splice`) and re-parsing is how :class:`~gmat_script.ast.script.Script` mutates while keeping
every *untouched* byte exact (D6). Working in bytes — not characters — is required because
tree-sitter node offsets are byte offsets into the UTF-8 source, and a comment may carry non-ASCII.

The two structural helpers compute the spans the mutators target: :func:`line_span` widens a node's
range to its whole physical line(s) (for removing or inserting statements), and
:func:`collect_reference_edits` walks the tree for every identifier that *refers to* a renamed
object — best-effort over the textual reference forms (dotted member roots, array-index / call
heads, bare operands, and the declaration name), deliberately **not** rewriting field-name segments,
the ``Create`` type, or text inside an opaque ``BeginScript`` body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from .base import node_text

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = ["MutationError", "detect_newline"]

# A bare GMAT identifier (a resource name or type): a letter / underscore start, then word chars.
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*", re.ASCII)
# A field path: dotted identifier segments. A property segment may lead with a digit (D13, e.g.
# ``Earth.3DModelFile``), so a segment is the looser ``\w+``.
_FIELD_PATH = re.compile(r"\w+(?:\.\w+)*", re.ASCII)


class MutationError(Exception):
    """A mutation was refused: it targets a script with syntax errors, would produce one, its edits
    overlap, or it was given a malformed name / field. The source is left unchanged when raised."""


def require_identifier(value: str, role: str) -> None:
    """Reject a resource *value* (a name or type) that is not a single bare GMAT identifier.

    A name carrying whitespace or a newline would splice extra ``Create`` names / statements into
    the configuration that re-parse cleanly (``Create Spacecraft "Bad Name"`` declares *two*
    objects), so the re-parse guard cannot catch it — validate the identifier up front instead.
    """
    if not _IDENTIFIER.fullmatch(value):
        raise MutationError(f"{role} {value!r} is not a valid GMAT identifier")


def require_field_path(value: str) -> None:
    """Reject a field path that is not dotted identifier segments.

    A field carrying a newline (or an embedded ``=``) would smuggle a second, independently-valid
    statement past the re-parse guard, so the field reference is validated before it is spliced.
    """
    if not _FIELD_PATH.fullmatch(value):
        raise MutationError(f"field {value!r} is not a valid field reference")


@dataclass(frozen=True, slots=True)
class _Edit:
    """One byte-range replacement: ``source[start:end]`` becomes *replacement* (raw UTF-8 bytes)."""

    start: int
    end: int
    replacement: bytes


def splice(source: bytes, edits: list[_Edit]) -> bytes:
    """Apply *edits* to *source* and return the new bytes; the edits must not overlap.

    Edits are addressed in the coordinates of the *original* source and applied high-offset-first,
    so earlier offsets stay valid as later spans are rewritten. Touching spans (one ends where the
    next begins) are allowed; a true overlap raises :class:`MutationError`.
    """
    ordered = sorted(edits, key=lambda edit: (edit.start, edit.end))
    for earlier, later in pairwise(ordered):
        if earlier.end > later.start:
            raise MutationError("overlapping edits cannot be applied")
    result = source
    for edit in sorted(edits, key=lambda edit: edit.start, reverse=True):
        result = result[: edit.start] + edit.replacement + result[edit.end :]
    return result


def line_span(source: bytes, start: int, end: int) -> tuple[int, int]:
    """Widen the byte range ``[start, end)`` to the whole physical line(s) it touches.

    Returns ``(line_start, line_end)`` where ``line_start`` is just past the preceding newline (or
    0) and ``line_end`` is just past the trailing newline (or end of source). The trailing ``\\n``
    is included so excising the span removes the entire line; a ``\\r\\n`` terminator goes with it
    because the ``\\r`` sits before the ``\\n`` inside the span. Multi-line constructs (a continued
    statement, a matrix, a block) widen from their first line to their last.
    """
    line_start = source.rfind(b"\n", 0, start) + 1  # rfind → -1 when on the first line, so → 0
    newline = source.find(b"\n", end)
    line_end = len(source) if newline == -1 else newline + 1
    return line_start, line_end


def detect_newline(text: str) -> str:
    """The newline for inserted lines: ``\\r\\n`` if the source uses it anywhere, else ``\\n``.

    The library never normalises existing line endings (D6); inserts just match the file.
    """
    return "\r\n" if "\r\n" in text else "\n"


def collect_reference_edits(root: Node, old: str, new: str) -> list[_Edit]:
    """Every edit needed to rewrite references to the object named *old* as *new* (best-effort).

    Walks the whole tree and rewrites each ``identifier`` whose text is *old* and whose syntactic
    role is an object reference: the root of a dotted ``member_expression``, the head of an
    array-index / call ``call_expression``, a bare operand / argument / list element, and the
    ``Create`` declaration name. It skips a ``member_expression`` *property* segment (a field name,
    e.g. the ``X`` in ``Other.X``) and the ``Create`` *type*, so renaming an object never disturbs a
    coincidentally-equal field name or type token. Identifiers inside an opaque ``BeginScript`` body
    are a single raw token, not parsed, so references there are not rewritten.
    """
    replacement = new.encode("utf-8")
    edits: list[_Edit] = []
    stack: list[Node] = [root]
    while stack:
        node = stack.pop()
        stack.extend(node.children)
        if node.type != "identifier" or node_text(node) != old:
            continue
        if not _is_object_reference(node):
            continue
        edits.append(_Edit(node.start_byte, node.end_byte, replacement))
    return edits


def _is_object_reference(node: Node) -> bool:
    """Whether an ``identifier`` whose text matched the renamed object actually *refers* to it."""
    parent = node.parent
    if parent is not None:
        if parent.type == "member_expression":
            prop = parent.child_by_field_name("property")
            if prop is not None and prop.id == node.id:
                return False  # a dotted field name (the suffix), not the object root
        elif parent.type == "create_command":
            type_node = parent.child_by_field_name("type")
            if type_node is not None and type_node.id == node.id:
                return False  # the declared GMAT type, not the object name
    return True


def declaration_name_edits(create_node: Node, old: str, new: str) -> list[_Edit]:
    """Rewrite ``Create`` declaration name(s) equal to *old*; references left untouched."""
    replacement = new.encode("utf-8")
    return [
        _Edit(name.start_byte, name.end_byte, replacement)
        for name in create_node.children_by_field_name("name")
        if node_text(name) == old
    ]
