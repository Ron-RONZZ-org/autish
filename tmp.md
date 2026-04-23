# bug fixes

- `verki generi` problem persist ! Fix it and test thoroughly !:

Unexpected truncation:
```
(autish-py3.12) rongzhou@libres:~/kodo/autish$ verki generi -i "Generate .enc on 'macOS'" -K /home/rongzhou/kodo/autish/AI-kuntekstoj/enc-AI-kunteksto.md -E ~/kodo/ronzz-markmap/encik/ECHO-IV.enc -m MiniMaxAI/MiniMax-M2.7:novita
[v] Skribita al /home/rongzhou/kodo/ronzz-markmap/encik/ECHO-IV.enc
terminologio.(eo,fr,en)="macOS"
difino.eo
```

# feature enhancement: incorporate generative AI function of `verki generi` into other `autish` commands

## `encik generi "{terminologio}"`

- generate `.enc` on `{terminologio}`
  - for now genearte only `terminologio` and `difino` fields
- `-tl/--terminologio-lingvo LANG-CODE1,LANGCODE,2...` the `terminologio` must be generated in those languages
- `-dl/--difino-lingvo LANG-CODE1,...` the `difino` must be generated in those languages
- common-sense verification: ensure generated content is valid `.enc` file.

## `retposto analizi {email UID}|{account-ID/email address}*`

- analyse one or more emails, taking into account of the entire conversation history
  - if nothing parsed analyse all unread mails that has NOT been previously analysed
  - if account(s) parsed limit to those accounts
- `-r/--resumi {celvojo}` resume the email content(s) in a `.md` file. Print to CLI if no `{celvojo}`
- `-k/--kalendaro {celvojo}` locate event details and export them to an `ics` file
- always create one single `.md`/`ics` file
- `-R/respondi {celvojo}` propose response(s). if {celvojo} not passed save the email as a draft in the DRAFT folder of the relevant account and inform user accordingly
  - if multiple `UID`, {celvojo} must be a folder. Each response draft will be saved as a separate file
- `--instrukcio/-i TEXT`: add custom instruction


## `retposto generi {konto-ID}|{konto-retpoŝto-adreso}|{celvoĵo}`

- `{konto-ID}|{lonto-retpoŝto-adreso}` specifies the account to save the AI-generated draft to
  - always save to DRAFT folder (not always literally named DRAFT, but must have such special property). Create one if not present.
- save to a file if {celvoĵo} parsed instead
- `--instrukcio/-i TEXT`: add custom instruction (REQUIRED)
- `--temo/-t TEXT`: write the mail subject manually and parse onto AI as reference
- `--al/-a` recipient address(es) and other relevant options from `retposto sendi`

## general requirements

- expose the context to be parsed to AI model in each AI-gen command in `~/.config/autish/verki/{function}-kunteksto.md` to allow user customization
  - provide a baseline context based on `autish` specifications
- each generative AI function should have AI model options like `--temperaturo/-tm` like in `verki generi` with sensible defaults for each usage case
- for `retposto analizi` and `retposto generi`, implement corresponding TUI functions in `retposto` TUI email view/compose-new pane

