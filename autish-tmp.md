À TESTER
# feature enhancements

## vorto

- `ligilo`: links are two way. Linking A to B should also link B to A, so that when user `vidi B`, A is shown in the ligiloj field.
- `tipo`: for nouns (substantivo), add a distinction of grammatical gender (`suf`female/`sum` male/ `su` both/neutral)
  - which is important in certain languages like français

## retposto

- `:h/:help` context hint should be visible whereever it is available
- markdown functions previously demanded not implemented

"""
- in message composition view (reply/forward/new), press m toggles on/off markdown interpretation
  - that is, whether the mail body is to be written in markdown
  - use `Mistune` python library to convert to HTML and send
    - also send a plain text version for compatibility
"""

- new: conversation view
  - currently, in message read view the right side space is empty
  - use it to display a conversation view if an email is part of a conversation (original+replies)
  - UI similar to main UI messages view
    - allow quick navigation toward other emails in the conversation
    - remember to implement the neovim navigation keys ! (use composable method to avoid unnecessary code duplication)
- also fix a small logic bug:
  - if user replies to an email sent by themselves, they meant probably to add something
  - so the reply receipient should be the original receipient, not themselves !
- new: reply all function: add appropriate CLI/interactive mode command/access keys

