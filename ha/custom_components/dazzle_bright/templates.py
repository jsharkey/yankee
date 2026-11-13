"""Template parsing: "name: dazzle_multicolor.py arguments" lines -> commands."""
from __future__ import annotations

import shlex

from . import dazzle_multicolor as dm


class TemplateError(ValueError):
    """A template line or command could not be parsed."""


def parse_templates(text: str) -> dict[str, str]:
    """Parse the options text into an ordered {name: args} dict.

    One template per line, "<name>: <args>". Blank lines and lines starting
    with "#" are ignored. Raises TemplateError naming the bad line.
    """
    templates: dict[str, str] = {}
    for lineno, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, args = line.partition(":")
        name, args = name.strip(), args.strip()
        if not sep or not name or not args:
            raise TemplateError(f"line {lineno}: expected '<name>: <arguments>', got {raw!r}")
        if name.lower() in (n.lower() for n in templates):
            raise TemplateError(f"line {lineno}: duplicate template name {name!r}")
        templates[name] = args
    return templates


def find_template(templates: dict[str, str], name: str) -> str | None:
    """Case-insensitive template lookup by name."""
    for key, args in templates.items():
        if key.lower() == name.strip().lower():
            return args
    return None


def build_argv(args: str, brightness_pct: int | None, point_count: int) -> list[str]:
    """Turn template arguments into a full dazzle_multicolor argv.

    Adds "-b <brightness>" (the light entity's brightness wins over any -b in
    the template) and "--points <point_count>" for static patterns that don't
    give one.
    """
    try:
        argv = shlex.split(args)
    except ValueError as err:
        raise TemplateError(str(err)) from None
    if not argv:
        raise TemplateError("empty command")
    if argv[0] == "static" and "--points" not in argv:
        argv += ["--points", str(point_count)]
    if brightness_pct is not None:
        argv = ["-b", str(brightness_pct)] + argv
    return argv


def build_payload(args: str, brightness_pct: int | None, point_count: int) -> tuple[bytes, int]:
    """Template arguments -> (raw payload, transport cmd_id)."""
    argv = build_argv(args, brightness_pct, point_count)
    try:
        payload, cmd_id, _ = dm.build_command(argv)
    except dm.CommandError as err:
        raise TemplateError(f"{args!r}: {err}") from None
    if payload is None:
        raise TemplateError(f"{args!r}: not a device command")
    return payload, cmd_id


def validate_templates(text: str, point_count: int) -> dict[str, str]:
    """Parse and dry-build every template; raises TemplateError on the first bad one."""
    templates = parse_templates(text)
    for name, args in templates.items():
        try:
            build_payload(args, 100, point_count)
        except TemplateError as err:
            raise TemplateError(f"template {name!r}: {err}") from None
    return templates
