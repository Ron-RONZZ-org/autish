# bug fix

## katex display

- certain complex equations are not displayed properly !
e.g., - $$\overrightarrow{F}_{e_1 \to e_2}=\frac{q_1 q_2}{4\pi \varepsilon_0}\frac{1}{r^2},\widehat{u}$$
- problem observed in: `md vidi` and `encik vidi --html`

## i18n

- certain help menu are still not in user locale.

With esperanto locale, there are still help content partially in English

(autish-py3.12) rongzhou@libres:~/kodo/autish$ autish -h
                                                                                                                                                                         
 Usage: autish [OPTIONS] COMMAND [ARGS]...                                                                                                                               
                                                                                                                                                                         
 Cross-platform CLI for essential tasks with minimum stimulation.                                                                                                        
                                                                                                                                                                         
╭─ Options ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --install-completion            Install completion for the current shell.                                                                                             │
│ --show-completion               Show completion for the current shell, to copy it or customize the installation.                                                      │
│ --help                -h        Show this message and exit.                                                                                                           │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ help        Show help (equivalent to autish -h).                                                                                                                      │
│ tempo       Print current local time and day of week.                                                                                                                 │
│ wifi        Wi-Fi management commands.                                                                                                                                │
│ bluhdento   Bluetooth device management commands.                                                                                                                     │
│ sistemo     Print system information.                                                                                                                                 │
│ kp          Execute a command and copy its output to clipboard.                                                                                                       │
│ shelo       Start an interactive autish shell (no need to type 'autish' each time).                                                                                   │
│ vorto       Mia Vorto — personal wordbook microapp.                                                                                                                   │
│ retposto    Retpoŝto — TUI email microapp.                                                                                                                            │
│ kontakto    Administri kontaktojn.                                                                                                                                    │
│ sekurkopio  Sekurkopio — backup & restore all autish user data.                                                                                                       │
│ uzanto      Uzanto — user profile and master-password management.                                                                                                     │
│ md          Markdown utilities: view in browser, export, and import.                                                                                                  │
│ encik       Encik — personal knowledge management microapp.                                                                                                           │
│ disko       Disko — storage device management.                                                                                                                        │
│ usb         USB device management commands.                                                                                                                           │
│ filmeto     Filmeto — trankvila navigado de filmetoj (nun: YouTube).                                                                                                  │
╰────────────────────────────────────────────────────────────────────────

Fix it !
