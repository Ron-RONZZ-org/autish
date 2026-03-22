COPILOT CLI
# bug fix

- critical: `sekurkopio auto` is not working ! I have a 60 minutes, keep maximum of 5 backup strategy set up, yet no backup except the initial one is done !
  - verify what is happening in the background and fix it !
  (autish-py3.12) rongzhou@libres:~/kodo/autish$ systemctl --user status autish-sekurkopio.timer
  journalctl --user -u autish-sekurkopio.service -f
● autish-sekurkopio.timer - Autish automatic backup timer
     Loaded: loaded (/home/rongzhou/.config/systemd/user/autish-sekurkopio.timer; enabled; preset: enabled)
     Active: active (waiting) since Sun 2026-03-22 14:37:42 CET; 3h 2min ago
    Trigger: Sun 2026-03-22 18:37:36 CET; 57min left
   Triggers: ● autish-sekurkopio.service

Mar 22 14:37:42 libres systemd[1359]: Started autish-sekurkopio.timer - Autish automatic backup timer.
Mar 22 14:37:42 libres systemd[1359]: Starting autish-sekurkopio.service - Autish automatic backup service...
Mar 22 14:37:42 libres sekurkopio[47538]: [*] 2026-03-22T13:37:42.939188+00:00
Mar 22 14:37:42 libres sekurkopio[47538]: [*] Komencante aŭtomatan sekurkopion...
Mar 22 14:37:49 libres sekurkopio[47538]: [✓] Sekurkopio kreita: autish_backup_20260322T133742.aut
Mar 22 14:37:49 libres systemd[1359]: Finished autish-sekurkopio.service - Autish automatic backup service.
Mar 22 14:37:49 libres systemd[1359]: autish-sekurkopio.service: Consumed 6.230s CPU time.

  - for info, I am running autish from source with poetry virtual environement. Any additional work required to make it work while running from source in dev mode ?
