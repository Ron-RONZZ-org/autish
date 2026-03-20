# bug fixes !


- The automatic `IMAP/SMTP` server detection mechanism in `retposto aldoni-konton` has just been fixed. Yet when `ENTER` is clicked on the newly added account `2`, `rong.zhou6@etu.univ-lorraine.fr`in interactive mode, nothing happens (no email list loaded). Figure out what went wrong and fix it.

# feature enhancements

- currently, there is no way to visualise attachments in received emails or add attachments when emailing others.
  - implement CLI/interactive mode function to open attachment in system default app, and joins attachments by entering file path(s) to outgoing messages.
