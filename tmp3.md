
# Bug Fixes and Feature Enhancements for `autish` CLI Tool

## Priority 1: Bug Fix - `verki generi` Truncation Issue

### Problem
The `verki generi` command truncates output unexpectedly. The generated `.enc` file is incomplete.

**Current behavior:**
```
(autish-py3.12) rongzhou@libres:~/kodo/autish$ verki generi -i "Generate .enc on 'macOS'" -K /home/rongzhou/kodo/autish/AI-kuntekstoj/enc-AI-kunteksto.md -E ~/kodo/ronzz-markmap/encik/ECHO-IV.enc -m MiniMaxAI/MiniMax-M2.7:novita
[v] Skribita al /home/rongzhou/kodo/ronzz-markmap/encik/ECHO-IV.enc
terminologio.(eo,fr,en)="macOS"
difino.eo
```

**Expected behavior:**
The output should include complete `.enc` file content with all required fields (not truncated after `difino.eo`).

**Action required:**
- Identify and fix the truncation logic
- Add comprehensive test cases to verify complete output generation
- Test with various input sizes and special characters


## Priority 2: Feature Enhancements

### Feature 2A: `encik generi "{terminologio}"` Command

**Purpose:** Generate `.enc` files for terminology entries with multilingual support.

**Syntax:**
```bash
encik generi "{terminologio}" [OPTIONS]
```

**Options:**
- `-tl, --terminologio-lingvo LANG-CODE1,LANG-CODE2,...`
  - Languages for terminology generation (e.g., `eo,fr,en`)
  - Required parameter
- `-dl, --difino-lingvo LANG-CODE1,LANG-CODE2,...`
  - Languages for definition generation (e.g., `eo,fr,en`)
  - Required parameter
- `-tm, --temperaturo FLOAT`
  - AI model temperature (creativity level)
  - Default: sensible value based on terminology generation use case
- `-i, --instrukcio TEXT`
  - Custom instruction for AI model
  - Optional
- other relevant AI model options similar to in `verki generi` (model name, etc.)

**Generated fields:**
- `terminologio` (in specified languages)
- `difino` (in specified languages)

**Validation:**
- Ensure generated content is valid `.enc` file format
- Verify all required fields are present and non-empty
- Test with edge cases (special characters, long strings, multiple languages)

---

### Feature 2B: `retposto analizi {identifier}` Command

**Purpose:** Analyze emails with consideration for full conversation history.

**Syntax:**
```bash
retposto analizi {email-UID|account-ID|email-address} [OPTIONS]
```

**Parameters:**
- `{identifier}` (required, repeatable)
  - Email UID, account ID, or email address
  - Can specify multiple identifiers separated by spaces
- If no identifier provided: analyze all unread emails that haven't been previously analyzed
 If account(s) specified: limit analysis to those accounts only

**Options:**
- `-r, --resumi {output-path}`
  - Generate markdown resume of email content(s)
  - If `{output-path}` provided: save to file
  - If not provided: print to CLI stout
- `-k, --kalendaro {output-path}`
  - Extract event details and export to `.ics` file
  - If `{output-path}` provided: save to file
  - If not provided: print to CLI and stout
- `-R, --respondi {output-path}`
  - Generate AI-proposed response(s)
  - If `{output-path}` provided: save drafts to that folder (one file per email)
  - If not provided: save to DRAFT folder in relevant account and notify user
  - For multiple emails: creates separate draft file for each
- `-i, --instrukcio TEXT`
  - Custom instruction for AI analysis
  - Optional
- `-tm, --temperaturo FLOAT`
  - AI model temperature
  - Default: sensible value for email analysis
- other relevant AI model options similar to in `verki generi` (model name, etc.)

**Output behavior:**
- Always create a single `.md` or `.ics` file per analysis type (even for multiple emails)
- Preserve email conversation history in analysis
- Include metadata (sender, date, account)

**TUI Integration:**
- Implement `retposto analizi` functionality in email view pane of `retposto` TUI
- Add "Analyze", "Resume", "Extract Events", "Generate Response" actions

---

### Feature 2C: `retposto generi {account-identifier}` Command

**Purpose:** Generate AI-written email drafts with custom instructions.

**Syntax:**
```bash
retposto generi {account-ID|email-address|output-path} [OPTIONS]
```

**Parameters:**
- `{account-identifier}` (required)
  - Account ID, email address, or output file path
  - Specifies where to save the generated draft

**Storage behavior:**
- Always save to DRAFT folder (or equivalent special folder with draft status)
- Create DRAFT folder if it doesn't exist
- If `{output-path}` provided: save to specified file instead

**Options:**
- `-i, --instrukcio TEXT` (REQUIRED)
  - Custom instruction/guidance for AI draft generation
- `-t, --temo TEXT`
  - Email subject line
  - Helps AI understand context
  - Optional
- `-a, --al RECIPIENT@EXAMPLE.COM` (repeatable)
  - Recipient email address(es)
  - Supports all options from `retposto sendi` command
- `-tm, --temperaturo FLOAT`
  - AI model temperature
  - Default: sensible value for email composition
- `-K, --kunteksto FILE-PATH`
  - Path to custom context file
  - Overrides default context
- other relevant AI model options similar to in `verki generi` (model name, etc.)


**TUI Integration:**
- Implement `retposto generi` functionality in compose-new pane of `retposto` TUI
- Show real-time draft generation preview
- Allow user to edit/refine before sending

---

## General Requirements for All AI-Generative Commands

### Context Management
1. **Configuration files:**
   - Location: `~/.config/autish/verki/{function}-kunteksto.md`
   - Purpose: Allow users to customize AI context/prompt

2. **Baseline context:**
   - Provide sensible default context files based on `autish` specifications
   - Document context variables and examples
   - Allow variables like `{lingvo}`, `{terminologio}`, `{tipo}`, etc.

### AI Model Configuration
3. **Standardize options across all AI-gen commands:**
   - `-tm, --temperaturo FLOAT` — AI creativity level
   - `-m, --modelo MODEL-ID` — Specify AI model (e.g., `MiniMaxAI/MiniMax-M2.7:novita`)
   - `-i, --instrukcio TEXT` — Custom instruction (where applicable)
   - `-K, --kunteksto FILE-PATH` — Custom context file path

4. **Default model settings:**
   - Set sensible defaults per command:
     - Terminology generation: lower temperature (precision-focused)
     - Email analysis: medium temperature (balanced)
     - Email composition: medium-low temperature (clarity-focused)
   - Document all defaults

### Testing Requirements
5. **Test coverage:**
   - Unit tests for each new command
   - Integration tests with real AI models
   - Edge cases: empty input, special characters, multiple languages, long content
   - Verify complete output (no truncation)
   - Validate generated file formats (`.enc`, `.md`, `.ics`)

# enhance integrated help globally

- current autish CLI integrated-help is completely insufficient
- many options are not listed in adequate detail for first time users
  - e.g.,for `autish todo serci`, the available values for `--stato` was not explained.
- to do now:
  -  plan and implement a global review of autish `--help` content
  - for options with restricted values (e.g. `stato` in `todo`), must exhaustively list options
    - Update `copilot-instructions.md` and your memory to save this behaviour as default in this repo
  - create detailed, `man` page for each autish command according to Linux/GNU convention

# vorto, encik DB efficiency enhancement

- as number of entries increased in `encik` and `vorto` databases, the time `aldoni` takes is becoming frustratingly long for new entries.
- plan and implement strategy to improve performance

# enhancements

```
rongzhou@libres:~/kodo/autish$ autish sistemo install
[i] autish jam instalita ĉe /home/rongzhou/.local/bin/autish
```

Should ask whether to reinstall (to fix bugs, etc.)

# bug fixes

remove the dummy entries you previously added to encik and vorto database for benchmarking, like `Fonto-f1cc7ab6 [Celo](#f386f930)`, etc.

# enhance integrated help globally

- current autish CLI integrated-help is completely insufficient
- many options are not listed in adequate detail for first time users
  - e.g.,for `autish todo serci`, the available values for `--stato` was not explained.
- to do now:
  -  plan and implement a global review of autish `--help` content
  - for options with restricted values (e.g. `stato` in `todo`), must exhaustively list options
    - Update `copilot-instructions.md` and your memory to save this behaviour as default in this repo
  - create detailed, `man` page for each autish command according to Linux/GNU convention


