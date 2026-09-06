"""Everything that touches an engine process.

The org contract's section 3 says the engine leaks in through exactly one
module, and netspec calls that boundary its migration plan. slicelab drives
more than one engine, so the boundary is drawn twice: ``subprocess`` lives only
in :mod:`slicelab.engine.launch`, and per-engine names and strings live only
under :mod:`slicelab.adapters`. Nothing here knows an engine's option names.
"""
