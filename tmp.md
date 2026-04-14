# feature enhancements

## `encik semantika`

- duplicate detection: if user tries to add an existing arc ( same `LIGILO`), display warning and ask for user (j/N) overwrite confirmation
- the content fetched from wikidata should be in user locale, with fallback in the order of language preference specified by user.
  - if non-found, fallback to Esperanto, then English
    - Update your `copilot-instructions.md` and memory to save this behaviour as default in autish
