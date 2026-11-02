"""Optional live grid-intensity feeds.

Offline-first by design: the engine runs entirely on committed sample data
with no network calls. A live feed (currently Electricity Maps) is used only
when explicitly requested and an API key is present, and it populates the
same GridIntensitySeries the sample curve does. See
docs/phase3-live-grid-feed.md.
"""
