COPILOT CLI
# Feature enhancements

- `filmeto agordo` > `filmeto agordi` to follow autish convention that commands should be verbs in original form whereever possible
  - Update your `copilot-instructions.md` and memory to save this behaviour as default in autish
- `filmeto agordi` should return summary of current settings in table format !
- any file paths displayed in autish should be clickable/copiable, just like URLs
  - e.g., in `filmeto agordi`

## `filmeto elsuti`

- if relative path is passed in `-v/--vojo`, should be relative to default path set in `filmeto agordi`
- show a summary of videos to be downloaded:
  - title
  - duration
  - author
  - size
  - destination location (including filename)
  - and ask for user confirmation (J/n)
