Philosophy
==========

autish is designed with a clear set of guiding principles that inform every
design decision.

Minimum Stimulation
-------------------

autish provides **calm, predictable output** with no unnecessary noise.
The interface avoids:

* Spinners and animations
* Excessive colour and visual clutter
* Verbose output unless explicitly requested
* Surprise behaviour or flashy prompts

The goal is to create a tool that respects the user's attention and cognitive
load, especially for neurodivergent users who may be sensitive to overstimulating
interfaces.

Sensible Defaults
-----------------

autish **works well out of the box** without requiring users to memorise
numerous options. When configuration is needed, it uses:

* Clear, self-explanatory command names (in Esperanto)
* Sensible fallback behaviour
* Minimal required arguments
* Helpful error messages with concrete examples

Esperanto Keywords
------------------

All command names and long option names are in **Esperanto**. This lowers the
barrier for non-English speakers and creates a more inclusive environment
where language is not a barrier to participation.

Examples: ``tempo``, ``wifi``, ``konekti``, ``malkonekti``, ``forigi``,
``horzono``, ``sistemo``, ``bluhdento``.

Short CLI flags may use any intuitive letter (e.g. ``-p`` for password/pasvorto).

Offline-First
-------------

Core functionality **works without internet access**. While some features
(like ``verki`` AI generation or ``encik`` semantic lookups) benefit from
connectivity, the essential tools remain fully functional offline.

Data is stored locally in SQLite databases under ``~/.local/share/autish/``.

Humble Scope
------------

Version 0.0.1 targets **Debian-based Linux** exclusively. The focus is on
doing a few things well rather than supporting everything immediately.

Supported platforms (v0.0.1):

* Ubuntu
* Debian
* Linux Mint
* Other Debian-based distributions

Neurodiversity-First Design
---------------------------

This project is designed with **neurodivergent people in mind** — that ethos
extends to our contributor community as well. We strive to be:

* Kind and patient in interactions
* Clear and direct in communication
* Inclusive of different communication styles
* Respectful of boundaries and sensory needs
