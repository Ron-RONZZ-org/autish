# New microapp: retpoŝto-TUI email app

## Main functionalities

### emailing

- allow connection to multiple email accounts
- fetch email from server
- send/reply/forward/delete email
  - cc/bcc

### email organisation

- flag to follow up
- create folders/subfolders and move email into/out of them

### spam prevention

- allow marking email as spam and/or block sender
  - if marked as spam, email from same sender are always marked as spam
- spam emails appear in spam folder

### contacts

- email addresses found in received/sent emails are automatically saved to a `koresponda listo` list
- user can import/export/create contacts in the `vcf` universal standard
- contact addresses are automatically proposed if a partial match is typed by user in sendto/cc/bcc

### filtering

- Sieve syntax for portability
- implement all relevant Sieve options (sendto/receipient/body/title (not) contains/is...)
