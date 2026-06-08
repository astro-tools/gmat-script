"""Canonical, idempotent re-emission of a GMAT script.

:func:`format` is a deterministic pretty-printer: it parses a script (or takes an already-parsed
tree) and re-emits it with canonical whitespace, per-resource grouping, consistent block
indentation, and normalised blank lines — safe to run on every save and as a pre-commit hook. It
never reorders resources, fields, or commands, so ``parse(format(x))`` stays structurally equal to
``parse(x)`` (the canonical-form contract is recorded as **D14** in ``docs/design/decisions.md``).

The canonical form, in brief:

- one statement per line (``...`` continuations folded away); a single space around ``=`` and
  binary operators; ``.`` and unary signs tight; ``{a, b}`` lists, ``[1, 1]`` index/call args, and
  ``[r1; r2]`` matrices follow the same structural conventions as
  :func:`~gmat_script.ast.emit_value`;
- each ``Create`` is glued to its own assignments with exactly one blank line before the next
  ``Create`` / ``#Include`` group and before ``BeginMissionSequence``; mission-sequence commands
  keep the author's blank lines (collapsed to at most one) to preserve grouping intent;
- four spaces of indentation per nesting level inside ``If`` / ``For`` / ``While`` / ``Target`` /
  ``Optimize`` blocks; a ``BeginScript`` body is preserved verbatim (opaque, D4);
- the only auto-fixes are dropping the redundant ``GMAT`` assignment prefix, dropping the optional
  trailing ``;``, and removing trailing whitespace; literal spellings (numbers, strings,
  identifiers) are preserved verbatim — formatting is pure layout;
- comments use a documented heuristic: an own-line comment attaches to the *following* statement
  (and is glued to it), a same-line comment stays trailing (kept with a ``;`` so a re-parse does
  not drop it), and blank gaps inside a comment run are kept (collapsed to at most one). A comment
  buried inside a value (a brace-list spanning lines, say) is rare; the statement holding it is
  re-emitted verbatim rather than folded, so the comment is never corrupted.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple

from .ast import Script
from .ast.base import BLOCK_HEADER_FIELDS, node_text
from .ast.edit import detect_newline
from .parser import Tree, parse

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = ["format"]

_INDENT = "    "  # four spaces per nesting level
_STYLES = frozenset({"canonical"})

# Top-level config statements that open a new resource group (one blank line before each).
_GROUP_OPENERS = frozenset({"create_command", "include", "begin_mission_sequence"})

# Block statements with a header line, an indented body, and a matched end keyword.
_BLOCK_END = {
    "if_statement": "EndIf",
    "for_statement": "EndFor",
    "while_statement": "EndWhile",
    "target_statement": "EndTarget",
    "optimize_statement": "EndOptimize",
}


def format(source: str | Tree | Script, style: str = "canonical") -> str:
    """Re-emit *source* in canonical form (see the module docstring for the conventions).

    :param source: the script text, or an already-parsed :class:`~gmat_script.Tree` /
        :class:`~gmat_script.Script`.
    :param style: the only supported value is ``"canonical"``; the parameter exists for future
        styles.
    :returns: the canonical source, ending in a single trailing newline (the file's own newline
        style is preserved; an empty script formats to ``""``).
    :raises ValueError: for an unknown *style*, or a script that has syntax errors (formatting a
        broken tree could corrupt it).
    :raises TypeError: for a *source* that is not a string, :class:`Tree`, or :class:`Script`.
    """
    if style not in _STYLES:
        raise ValueError(f"unknown style {style!r} (supported: {sorted(_STYLES)})")
    tree = _resolve_tree(source)
    if tree.has_errors:
        raise ValueError("cannot format a script that has syntax errors")
    newline = detect_newline(tree.text)
    lines = _emit_source_file(tree.root_node)
    return newline.join(lines) + newline if lines else ""


def _resolve_tree(source: str | Tree | Script) -> Tree:
    """Coerce the accepted input forms to a :class:`Tree`."""
    if isinstance(source, str):
        return parse(source)
    if isinstance(source, Tree):
        return source
    if isinstance(source, Script):
        return source.tree
    raise TypeError(f"cannot format a {type(source).__name__!r}; expected str, Tree, or Script")


# -- the top level: split config from the mission sequence ----------------------------------------


def _emit_source_file(root: Node) -> list[str]:
    """Emit the whole file: the configuration section, then the mission sequence."""
    children = list(root.children)
    marker = next(
        (i for i, child in enumerate(children) if child.type == "begin_mission_sequence"), None
    )
    if marker is None:
        return _emit_sequence(children, 0, in_config=True)
    config = _emit_sequence(children[: marker + 1], 0, in_config=True)
    sequence = _emit_sequence(children[marker + 1 :], 0, in_config=False)
    if sequence:
        config.append("")  # one blank line after BeginMissionSequence
        config.extend(sequence)
    return config


# -- a sequence of statements + interspersed comments at one indentation level --------------------


# A rendering unit: either a statement with its leading comments and an optional trailing comment,
# or a run of orphan comments that no statement follows (a comment-only tail of a block / file).
class _StmtUnit(NamedTuple):
    statement: Node
    leading: list[Node]
    trailing: Node | None


class _CommentUnit(NamedTuple):
    comments: list[Node]


def _emit_sequence(items: list[Node], indent: int, *, in_config: bool) -> list[str]:
    """Render *items* (statements and comments, in source order) at *indent*."""
    units = _partition(items)
    lines: list[str] = []
    for index, unit in enumerate(units):
        if lines and _blank_before(unit, units[index - 1], in_config=in_config):
            lines.append("")
        if isinstance(unit, _CommentUnit):
            lines.extend(_render_comment_run(unit.comments, indent))
            continue
        lines.extend(_render_comment_run(unit.leading, indent))
        statement_lines = _emit_statement(unit.statement, indent)
        if unit.trailing is not None and statement_lines:
            statement_lines[-1] = _with_trailing_comment(statement_lines[-1], unit.trailing)
        lines.extend(statement_lines)
    return lines


def _partition(items: list[Node]) -> list[_StmtUnit | _CommentUnit]:
    """Group *items* into statement units (with their leading / trailing comments) and a final run
    of orphan comments, if any."""
    units: list[_StmtUnit | _CommentUnit] = []
    leading: list[Node] = []
    index = 0
    count = len(items)
    while index < count:
        item = items[index]
        if item.type == "comment":
            leading.append(item)  # own-line comment → leads the next statement
            index += 1
            continue
        trailing: Node | None = None
        nxt = items[index + 1] if index + 1 < count else None
        if nxt is not None and nxt.type == "comment" and nxt.start_point[0] == item.end_point[0]:
            trailing = nxt  # same-line comment → trails this statement
            index += 1
        units.append(_StmtUnit(item, leading, trailing))
        leading = []
        index += 1
    if leading:
        units.append(_CommentUnit(leading))
    return units


def _render_comment_run(comments: list[Node], indent: int) -> list[str]:
    """Render a run of own-line comments, preserving a single blank where the author left one."""
    lines: list[str] = []
    for position, comment in enumerate(comments):
        if position and comment.start_point[0] - comments[position - 1].end_point[0] >= 2:
            lines.append("")
        lines.append(_line(indent, _comment_text(comment)))
    return lines


def _blank_before(
    unit: _StmtUnit | _CommentUnit, previous: _StmtUnit | _CommentUnit, *, in_config: bool
) -> bool:
    """Whether to emit one blank line before *unit*.

    In the configuration section the blank lines are structural — one before every resource-group
    opener (``Create`` / ``#Include`` / ``BeginMissionSequence``), none elsewhere — so a ``Create``
    stays glued to its assignments. In the mission sequence the author's blank lines are preserved
    (collapsed to at most one), keeping their grouping intent.
    """
    if in_config:
        return isinstance(unit, _StmtUnit) and unit.statement.type in _GROUP_OPENERS
    return _unit_first_row(unit) - _unit_last_row(previous) >= 2


def _unit_first_row(unit: _StmtUnit | _CommentUnit) -> int:
    if isinstance(unit, _CommentUnit):
        return unit.comments[0].start_point[0]
    return (unit.leading[0] if unit.leading else unit.statement).start_point[0]


def _unit_last_row(unit: _StmtUnit | _CommentUnit) -> int:
    if isinstance(unit, _CommentUnit):  # pragma: no cover - a comment run is never a predecessor
        return unit.comments[-1].end_point[0]
    return (unit.trailing if unit.trailing is not None else unit.statement).end_point[0]


# -- statement emission ---------------------------------------------------------------------------


def _emit_statement(node: Node, indent: int) -> list[str]:
    """Emit one statement as one or more fully-indented lines."""
    kind = node.type
    if kind in _BLOCK_END:
        return _emit_block(node, indent)
    if kind == "script_block":
        return _emit_script_block(node, indent)
    if _has_inner_comment(node):
        # A comment buried inside a value can't be folded onto one line without eating it; keep the
        # statement verbatim so the comment survives.
        return _emit_verbatim(node, indent)
    if kind == "create_command":
        return [_line(indent, _emit_create(node))]
    if kind == "assignment_command":
        return [_line(indent, _emit_assignment(node))]
    if kind == "function_call_command":
        return [_line(indent, _emit_function_call(node))]
    if kind == "function_definition":
        return [_line(indent, _emit_function_definition(node))]
    if kind == "include":
        return [_line(indent, f"#Include {_inline(node.child_by_field_name('path'))}")]
    if kind == "begin_mission_sequence":
        return [_line(indent, "BeginMissionSequence")]
    if kind == "command":
        return [_line(indent, " ".join(_emit_inline(child) for child in node.named_children))]
    return _emit_verbatim(node, indent)  # pragma: no cover - every statement type is handled above


def _emit_create(node: Node) -> str:
    """``Create <Type> <name>[ <name> …]``, each name carrying its ``[r, c]`` size if any."""
    parts = ["Create", _text(node.child_by_field_name("type"))]
    name_ids = {name.id for name in node.children_by_field_name("name")}
    chunk = ""
    for child in node.named_children:
        if child.id in name_ids:
            if chunk:
                parts.append(chunk)
            chunk = node_text(child)
        elif child.type == "array_size":
            chunk += _emit_array_size(child)
    if chunk:  # pragma: no cover - a Create always has at least one name
        parts.append(chunk)
    return " ".join(parts)


def _emit_assignment(node: Node) -> str:
    """``[label ]<lhs> = <rhs>`` — the redundant leading ``GMAT`` keyword is dropped."""
    label = node.child_by_field_name("label")
    prefix = f"{node_text(label)} " if label is not None else ""
    left = _inline(node.child_by_field_name("left"))
    right = _inline(node.child_by_field_name("right"))
    return f"{prefix}{left} = {right}"


def _emit_function_call(node: Node) -> str:
    """``[out, …] = name(args)`` (D4)."""
    outputs = _inline(node.child_by_field_name("outputs"))
    function = _inline(node.child_by_field_name("function"))
    return f"{outputs} = {function}"


def _emit_function_definition(node: Node) -> str:
    """``function [[out, …] = ]name[(param, …)]`` — the ``.gmf`` header (D10)."""
    name = node.child_by_field_name("name")
    outputs = [
        child
        for child in node.named_children
        if child.type == "identifier" and name is not None and child.start_byte < name.start_byte
    ]
    head = "function "
    if outputs:
        head += "[" + ", ".join(node_text(out) for out in outputs) + "] = "
    head += _text(name)
    parameters = _find_child(node, "parameter_list")
    if parameters is not None:
        head += _emit_inline(parameters)
    return head


# -- blocks ---------------------------------------------------------------------------------------


def _emit_block(node: Node, indent: int) -> list[str]:
    """A control-flow / solver block: header line, indented body, matched end keyword."""
    body = _body_children(node)
    if _header_has_comment(node):
        # A comment buried inside a header value (a multi-line ``{…}`` options block, a ``For``
        # range, an ``If`` condition) can't be folded onto one line without commenting out the rest
        # of it, so the header is emitted verbatim — the same guard ``_emit_statement`` applies to a
        # simple statement, which a block never reaches because it dispatches here first.
        lines = _emit_verbatim_header(node, indent)
    else:
        header, header_row = _block_header(node)
        if body and body[0].type == "comment" and body[0].start_point[0] == header_row:
            header = _with_trailing_comment(header, body[0])  # comment trailing the header line
            body = body[1:]
        lines = [_line(indent, header)]
    lines.extend(_emit_sequence(body, indent + 1, in_config=False))
    else_clause = _find_child(node, "else_clause")
    if else_clause is not None:
        else_body = [child for child in else_clause.children if child.is_named]
        else_line = _line(indent, "Else")
        if (
            else_body
            and else_body[0].type == "comment"
            and (else_body[0].start_point[0] == else_clause.start_point[0])
        ):
            else_line = _with_trailing_comment(else_line, else_body[0])
            else_body = else_body[1:]
        lines.append(else_line)
        lines.extend(_emit_sequence(else_body, indent + 1, in_config=False))
    lines.append(_line(indent, _BLOCK_END[node.type]))
    return lines


def _block_header(node: Node) -> tuple[str, int]:
    """The block's header line, and the source row it ends on (to pick up a trailing comment)."""
    kind = node.type
    label = node.child_by_field_name("label")
    prefix = f"{node_text(label)} " if label is not None else ""
    if kind == "if_statement":
        header = f"If {prefix}{_inline(node.child_by_field_name('condition'))}"
    elif kind == "while_statement":
        header = f"While {prefix}{_inline(node.child_by_field_name('condition'))}"
    elif kind == "for_statement":
        variable = _inline(node.child_by_field_name("variable"))
        header = f"For {prefix}{variable} = {_inline(node.child_by_field_name('range'))}"
    else:
        keyword = "Target" if kind == "target_statement" else "Optimize"
        options = node.child_by_field_name("options")
        suffix = f" {_emit_inline(options)}" if options is not None else ""
        header = f"{keyword} {prefix}{_inline(node.child_by_field_name('solver'))}{suffix}"
    return header, _header_row(node)


def _header_row(node: Node) -> int:
    """The last source row spanned by the block's header fields."""
    row = node.start_point[0]
    for name in BLOCK_HEADER_FIELDS:
        field = node.child_by_field_name(name)
        if field is not None:
            row = max(row, field.end_point[0])
    return row


def _header_end_byte(node: Node) -> int:
    """The byte offset just past the block's last header field — where its body begins."""
    header_end = node.start_byte
    for name in BLOCK_HEADER_FIELDS:
        field = node.child_by_field_name(name)
        if field is not None:
            header_end = max(header_end, field.end_byte)
    return header_end


def _header_has_comment(node: Node) -> bool:
    """Whether a comment sits inside the block's header span (within or between its header fields).

    A comment *trailing* the header line (after the last field) starts at / past
    :func:`_header_end_byte`, so it is not a header comment — it is picked up as a trailing comment
    on the normal path; only a comment the header would have to fold over counts here.
    """
    header_end = _header_end_byte(node)
    stack = list(node.children)
    while stack:
        child = stack.pop()
        if child.start_byte >= header_end:
            continue
        if child.type == "comment":
            return True
        stack.extend(child.children)
    return False


def _body_children(node: Node) -> list[Node]:
    """The block's body statements + comments (between the header and the end / ``Else``)."""
    header_end = _header_end_byte(node)
    return [
        child
        for child in node.children
        if child.start_byte >= header_end and child.is_named and child.type != "else_clause"
    ]


def _emit_script_block(node: Node, indent: int) -> list[str]:
    """``BeginScript … EndScript`` — the body is opaque, preserved verbatim (D4).

    Only the ``BeginScript`` line is re-indented and only the file's newline is normalised; the body
    and ``EndScript`` are emitted exactly as written (the opaque body may carry an inline label, its
    own indentation, and trailing whitespace that the formatter must not touch)."""
    lines = _normalise_newlines(node_text(node)).split("\n")
    lines[0] = _line(indent, lines[0].lstrip())
    return lines


def _emit_verbatim(node: Node, indent: int) -> list[str]:
    """Re-emit a statement from its source slice (newline-normalised, trailing whitespace trimmed),
    indenting only its first line — the fallback for a statement with a comment inside a value."""
    return _verbatim_lines(node_text(node), indent)


def _emit_verbatim_header(node: Node, indent: int) -> list[str]:
    """Re-emit just a block's header (up to :func:`_header_end_byte`) verbatim — the fallback when a
    comment is buried in a header value. The body and end keyword are emitted normally by the
    caller, so only the header lines are preserved as written."""
    raw = node.text
    header_text = raw[: _header_end_byte(node) - node.start_byte].decode("utf-8") if raw else ""
    return _verbatim_lines(header_text, indent)


def _verbatim_lines(text: str, indent: int) -> list[str]:
    """*text* as physical lines, newline-normalised and trailing-whitespace-trimmed, indenting only
    the first line (continuation lines keep their authored column)."""
    raw = _normalise_newlines(text).split("\n")
    return [_line(indent, raw[0].rstrip()), *(physical.rstrip() for physical in raw[1:])]


# -- inline (single-line) emission of expressions, references, and values -------------------------


def _emit_inline(node: Node) -> str:
    """Emit an expression / reference / value node on a single line, folding any continuation."""
    handler = _INLINE.get(node.type)
    if handler is not None:
        return handler(node)
    if node.type == "unquoted_value":
        return node_text(
            node
        ).rstrip()  # GMAT rest-of-line value; drop captured trailing whitespace
    return node_text(node)  # numbers, strings, identifiers, command labels, keywords: verbatim


def _emit_member(node: Node) -> str:
    obj = _inline(node.child_by_field_name("object"))
    return f"{obj}.{_text(node.child_by_field_name('property'))}"


def _emit_call(node: Node) -> str:
    function = _inline(node.child_by_field_name("function"))
    return f"{function}{_inline(node.child_by_field_name('arguments'))}"


def _emit_argument_list(node: Node) -> str:
    return "(" + ", ".join(_emit_inline(child) for child in node.named_children) + ")"


def _emit_output_list(node: Node) -> str:
    return "[" + ", ".join(node_text(child) for child in node.named_children) + "]"


def _emit_parameter_list(node: Node) -> str:
    return "(" + ", ".join(node_text(child) for child in node.named_children) + ")"


def _emit_array_size(node: Node) -> str:
    return "[" + ", ".join(node_text(child) for child in node.named_children) + "]"


def _emit_list(node: Node) -> str:
    return "{" + ", ".join(_emit_inline(child) for child in node.named_children) + "}"


def _emit_option_assignment(node: Node) -> str:
    left = _inline(node.child_by_field_name("left"))
    return f"{left} = {_inline(node.child_by_field_name('right'))}"


def _emit_unary(node: Node) -> str:
    operator = _text(node.child_by_field_name("operator"))
    return f"{operator}{_inline(node.child_by_field_name('operand'))}"


def _emit_binary(node: Node) -> str:
    left = _inline(node.child_by_field_name("left"))
    operator = _text(node.child_by_field_name("operator"))
    return f"{left} {operator} {_inline(node.child_by_field_name('right'))}"


def _emit_parenthesized(node: Node) -> str:
    return f"({_emit_inline(node.named_children[0])})"


def _emit_array_literal(node: Node) -> str:
    rows: list[list[str]] = [[]]
    for child in node.children:
        if child.is_named:
            rows[-1].append(_emit_inline(child))
        elif node_text(child) == ";":
            rows.append([])
    return "[" + "; ".join(" ".join(row) for row in rows) + "]"


def _emit_for_range(node: Node) -> str:
    parts = [_inline(node.child_by_field_name("from")), _inline(node.child_by_field_name("to"))]
    by = node.child_by_field_name("by")
    if by is not None:
        parts.append(_emit_inline(by))
    return ":".join(parts)


_INLINE: dict[str, Callable[[Node], str]] = {
    "member_expression": _emit_member,
    "call_expression": _emit_call,
    "argument_list": _emit_argument_list,
    "output_list": _emit_output_list,
    "parameter_list": _emit_parameter_list,
    "array_size": _emit_array_size,
    "list": _emit_list,
    "option_assignment": _emit_option_assignment,
    "unary_expression": _emit_unary,
    "binary_expression": _emit_binary,
    "parenthesized_expression": _emit_parenthesized,
    "array_literal": _emit_array_literal,
    "for_range": _emit_for_range,
}


# -- small helpers --------------------------------------------------------------------------------


def _line(indent: int, text: str) -> str:
    return _INDENT * indent + text


def _comment_text(node: Node) -> str:
    """A comment's text with trailing whitespace removed (a ``% …`` token captures the rest of the
    line, including the ``\\r`` of a CRLF terminator — strip it so re-joining stays clean)."""
    return node_text(node).rstrip()


def _with_trailing_comment(line: str, comment: Node) -> str:
    """Append a same-line *comment* to *line*, terminating the statement with ``;`` first.

    The ``;`` is required: a comment that sits between a statement's last token and the newline is
    dropped on re-parse unless an explicit ``;`` terminates the statement (the newline-as-terminator
    otherwise swallows it), which would lose the comment on the next format pass.
    """
    return f"{line}; {_comment_text(comment)}"


def _inline(node: Node | None) -> str:
    return _emit_inline(node) if node is not None else ""


def _text(node: Node | None) -> str:
    return node_text(node) if node is not None else ""


def _find_child(node: Node, kind: str) -> Node | None:
    return next((child for child in node.children if child.type == kind), None)


def _has_inner_comment(node: Node) -> bool:
    """Whether a comment node sits inside *node*'s own span (e.g. within a multi-line value)."""
    stack = list(node.children)
    while stack:
        child = stack.pop()
        if child.type == "comment":
            return True
        stack.extend(child.children)
    return False


def _normalise_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
