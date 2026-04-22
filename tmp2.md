# `verki` enhancement

- add a `kampo` in `uzanto profilo` allowing user to specify `--api-slosilo`(j) for different inference providers 
- move the core functionality of `verki` to `verki generi` subcommand, and add alias for the options
  - utilise autish alias naming fallback convention to avoid conflicts: 1st letter in lowercase>  in uppercase> first letter of each word
    - Update `copilot-instructions.md` and your memory to save this behaviour as default in this repo
- add `verki modelo {provider}` function to allow browsing available models
  - `-n/--nomo` allow searching model by name
- add detailed markdown documentation on verki on setup, options, and usage examples and link to it in `README.md`
