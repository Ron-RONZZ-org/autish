# feature enhancements

## vorto

- `aldoni,modifi`: if `-l fr`, `oe` is automatically interpreted as `œ` in difinio/teksto, etc., since in French words `oe` is always written as `œ`
- `vidi`: always attempt to show closest matches if no exact match found, ask user interactively to select one match to show if multiple approximate matchs found (max 5). Interpret `oe` and `œ` interchangeably searching for closest match. Ignore letter case.

# new: `md`

- markdown related functions
  - `md vidi {path/url}` visualise markdown in default browser
    - katex formula support (`$...$ $$...$$` or `\[...\]` delimters)
    - all title levels are collapsable/extendable to hide and view subcontent
      - `--faldnivelo/-f {number}` fold at nth level title on render
  - `md eksporti {source path/url} {destination path}`
    - export `.md` file as html (rendered as in `vidi` but exported to a file)
    - `--formato/-f pdf` export as pre-rendered pdf instead of HTML
