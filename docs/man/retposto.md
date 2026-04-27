# retposto(1)

## NAME

retposto - Retpoŝto — TUI retpoŝta mikroapo.

## SYNOPSIS

```
autish retposto [SUBCOMMAND] [OPTIONS]...
```

## DESCRIPTION

Retpoŝto — TUI retpoŝta mikroapo.

For more information about autish, see autish(1).

## SUBCOMMANDS

- `aldoni-konton        Add a new email account (interactive if options omitted).`
- `forigi-konton        Remove an email account.`
- `listigi-kontojn      List configured email accounts.`
- `preni                Fetch new mail from server(s).`
- `sendi                Send an email from the command line.`
- `vidi                 View one fetched message in CLI by composite UID.`
- `serci                Serĉi mesaĝojn en loka retpoŝta datumbazo.`
- `respondi             Reply to one message from CLI.`
- `respondi-ciujn       Reply-all to one message from CLI.`
- `plusendi             Forward one message from CLI.`
- `bloki                Block a sender or domain from appearing in inbox.`
- `malbloki             Remove a sender/domain from the block list.`
- `blok-listo           Show all blocked senders/domains.`
- `ĝisdatigi-konton     Update IMAP/SMTP credentials for an existing account.`
- `subskribo            View or set the email signature for an account.`
- `novdos               Create a new folder (or sub-folder) under an account.`
- `listigi-dosierujojn  List folders for one or all accounts.`
- `movi-mesagon         Move a message to a different folder.`
- `kopii-mesagon        Copy a message to a different folder.`
- `renomi-dosierujon    Rename a folder.`
- `movi-dosierujon      Move a folder under another folder (as sub-folder).`
- `reordigi-konton      Move account display order up/down by one.`
- `eksporti             Export all retposto user data as an encrypted archive.`
- `importi              Import email account configs from an encrypted archive or legacy export.`
- `konton               Open all email accounts in the system terminal editor for direct editing.`
- `listigi-aldonajojn   List attachments for a message.`
- `malfermi-aldonajon   Open an attachment with the system default app.`
- `marki-legita         Mark all messages in a folder as read.`
- `kontakto             Administri kontaktojn (koresponda listo).`
- `filtro               Administri Sieve-stilajn mesaĝ-filtrilojn.`


## OPTIONS

Run `autish retposto --help` to see all available options.

## EXAMPLES

```bash
# Show help for this command
autish retposto --help

# Show help for a specific subcommand
autish retposto SUBCOMMAND --help
```

## AUTHOR

Autish contributors

## SEE ALSO

autish(1), autish-retposto(1)
