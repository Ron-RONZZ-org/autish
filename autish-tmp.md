# feature enhancements

## `retposto`

- previously, we handled email sending failure by saving it as draft. The better approch is to add it to a dedicated `OUTBOX` folder where user can send all with one `ctrl+shift+s` or one by one with `ctrl+s` directly in the messages list view, by accessing the special folder.

- TUI for priority and read confirmation is confusing. Standardise to universal email standards. Also, why is the read confirmation a free text field in TUI ? Makes zero sense.
- TUI for `from/to/cc/bcc` still not offering typing suggestions. Fix !
- I tried sending an email from my added account rong.zhou6@etu.univ-lorraine.fr twiced and failed twice. Investigate what happened and debug !
