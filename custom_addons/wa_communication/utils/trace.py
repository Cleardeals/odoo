"""Correlation-id (``trace_id``) plumbing for Odoo-side WhatsApp logs.

The WA platform mints a ``trace_id`` at ingress and carries it on every Pub/Sub
message attribute (see the ``cleardeals-whatsapp-platform`` shared logging).  The
push controller binds it for the duration of each ``/wa/pubsub/push`` request so
that **every** ``_logger`` line emitted while handling that event is prefixed
with ``[trace=<id>]`` — letting you follow one message from the platform straight
into Odoo's server log, and cross-reference it against the ``wa.event.log`` row
that stores the same id.

Native stdlib logging only — no third-party dependency.  The design is a single
``contextvars.ContextVar`` (async/thread-safe) plus a :class:`logging.Filter`
that prepends the bound id.  When nothing is bound (the normal case for non-WA
requests) the filter is a no-op, so it is safe to attach process-wide.
"""

import contextlib
import contextvars
import logging

# Thread/async-local holder for the current trace id. Default ``None`` → the
# filter adds nothing, so ordinary Odoo logging is completely unaffected.
_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "wa_trace_id", default=None
)


def get_trace_id() -> str | None:
    """Return the trace id bound to the current context, or ``None``."""
    return _trace_id.get()


@contextlib.contextmanager
def trace_context(trace_id: str | None):
    """Bind ``trace_id`` for the duration of the ``with`` block, then restore.

    A falsy ``trace_id`` binds nothing (the block runs untraced), so callers can
    pass ``attributes.get('trace_id')`` unconditionally.
    """
    if not trace_id:
        yield
        return
    token = _trace_id.set(trace_id)
    try:
        yield
    finally:
        _trace_id.reset(token)


class _TraceFilter(logging.Filter):
    """Prepend ``[trace=<id>]`` to a record's message when a trace is bound.

    Implemented by rewriting ``record.msg`` (after Odoo's own formatting has been
    resolved via ``getMessage()``) so the id shows up inside Odoo's existing log
    format without needing any server-config change.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        trace_id = _trace_id.get()
        if trace_id:
            record.msg = "[trace=%s] %s" % (trace_id, record.getMessage())
            record.args = ()
        return True


_INSTALLED = False


def install_trace_filter() -> None:
    """Attach the trace filter to the root logger's handlers (idempotent).

    Attaching at the handler level (rather than a single logger) means every log
    line emitted during a traced request — including nested model logs — carries
    the id, which is exactly the correlation we want. Outside a traced request the
    filter does nothing.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    root = logging.getLogger()
    trace_filter = _TraceFilter()
    for handler in root.handlers:
        handler.addFilter(trace_filter)
    _INSTALLED = True
