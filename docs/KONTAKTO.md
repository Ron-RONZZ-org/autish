# Kontakto — Contact Management

Autish kontakto is a lightweight, offline-first contact management system with support for markdown linking to encik and vorto entries.

## Overview

**kontakto** lets you:
- **Add** contacts with multiple phone numbers and email addresses
- **Modify** contact information
- **Delete** contacts (with undo support)
- **Search** contacts with fuzzy matching
- **View** contact details
- **Manage** contact categories
- **Link** to knowledge entries and words via markdown

## Database Storage

Contacts are stored in the `retposto` module's SQLite database. Each contact has a unique UUID and supports multiple phone numbers, email addresses, and custom fields.

## Markdown Links in Notes

Contact notes support markdown links to **encik** (encyclopedia) entries and **vorto** (word) entries. This allows you to connect your contacts to your knowledge base and vocabulary:

### Link Formats

- **Encik link:** `[Entry Name](ec#uuid)` → Links to encik entry
- **Vorto link:** `[Word](vt#uuid)` → Links to vorto entry

Where `uuid` is an 8-character hex identifier.

### Adding Contacts with Links

```bash
kontakto aldoni -n "Alice Johnson" -r "alice@example.com" -N "Works on [Machine Learning](ec#12345678) projects"
```

### Viewing Links

When you view a contact with `kontakto vidi`, markdown links are rendered as clickable Rich links in the CLI:

```
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Kampo  ┃ Valoro                          ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ nomo   │ Alice Johnson                   │
│ noto   │ Works on Machine Learning projects
└────────┴─────────────────────────────────┘
```

## Commands

### Add Contact

```bash
kontakto aldoni -n "John Doe" -r "john@example.com" -t "+33612345678"
```

**Common Options:**
- `-n, --nomo TEXT`: First name
- `-F, --familia-nomo TEXT`: Last name
- `-o, --organizo TEXT`: Organization
- `-r, --retposhtadreso TEXT`: Email address (repeatable)
- `-t, --telefonnumero TEXT`: Phone number (repeatable)
- `-p, --postadreso TEXT`: Postal address
- `-d, --naskig-dato YYYYMMDD`: Birth date
- `-N, --noto TEXT`: Notes (supports markdown links)
- `-k, --kategorio TEXT`: Category (repeatable)
- `-l, --lingvoj TEXT`: Languages (e.g., en,fr)

### View Contact

```bash
kontakto vidi john@example.com
kontakto vidi "#12345678"
```

Shows all contact details including linked notes.

### Modify Contact

```bash
kontakto modifi "#12345678" -n "Jane Doe"
kontakto modifi "jane@example.com" -N "Updated notes with [new link](ec#87654321)"
```

### Search Contacts

```bash
# Fuzzy search
kontakto serci "john" --fuzzy

# Filter by organization
kontakto serci --organizo "TechCorp"

# Filter by language
kontakto serci -l en,fr
```

### Delete Contact

```bash
kontakto forigi "#12345678"
kontakto forigi "#12345678" --justa  # Skip confirmation
```

### Undo Changes

```bash
kontakto malfari
```

Undoes the last 10 modifications.

### List All Contacts

```bash
kontakto ls
```

## Auto-Primary Contact Fields

When you provide a single phone number or email without explicit labels, autish automatically assigns it the "ĉefa" (primary) label:

```bash
# These are equivalent:
kontakto aldoni -n "Alice" -t "0033612345678"
kontakto aldoni -n "Alice" -t "0033612345678:ĉefa:prima"
```

## Duplicate Handling

When adding a contact that matches an existing one, autish prompts you with three options:

- **a** (anstataŭigi): Update the existing contact
- **k** (krei nova): Create a new contact anyway
- **N** (nuligi): Cancel (default)

```
Kontakto simila al john@example.com jam ekzistas. 
Elektu: (a/k/N):
```

## Examples

### Create a Contact with Knowledge Links

```bash
kontakto aldoni \
  -n "Dr. Marie" \
  -F "Curie" \
  -o "University of Paris" \
  -r "marie@paris.fr" \
  -N "Expert in [Radioactivity](ec#11111111) and [Chemistry](ec#22222222). See also [physicist](vt#33333333)."
```

### Update Contact with New Notes

```bash
kontakto modifi "marie@paris.fr" \
  -N "Updated expertise: [Polonium](ec#44444444), [Radium](ec#55555555)"
```

### Organize by Category

```bash
kontakto aldoni -n "Bob" -r "bob@work.com" -k "work" -k "developers"
kontakto serci -k work
```

### Search with Multiple Filters

```bash
# Find work contacts who speak French
kontakto serci -k work -l fr

# Find all contacts in a specific organization
kontakto serci --organizo "TechCorp"
```

## Technical Details

### Contact Fields

- **uuid**: Unique 8-character identifier (auto-generated)
- **nomo**: First name
- **familia_nomo**: Last name
- **organizo**: Organization name
- **naskig_dato**: Birth date (YYYYMMDD format)
- **naskig_loko**: Birth place
- **organiza_identiga_numero**: Organization ID number
- **retposhtadresoj**: Multiple email addresses with labels/priorities
- **telefonnumeroj**: Multiple phone numbers with labels/priorities
- **postadreso**: Mailing address
- **lingvoj**: Languages spoken
- **kategorioj**: Contact categories
- **kampoj**: Custom key-value fields
- **noto**: Notes (supports markdown links)
- **konfirmita**: Confirmation status (0=unconfirmed, 1=confirmed)
- **modifita_je**: Last modification timestamp

### Markdown Link Validation

- Links are validated at display time
- Invalid UUIDs are gracefully ignored
- Missing target entries don't prevent contact viewing
- Links render as clickable Rich text in CLI

## Tips and Tricks

### Bulk Add Contacts

Use shell loops to add multiple contacts:

```bash
while read line; do
  kontakto aldoni -n "$line"
done < contacts.txt
```

### Export to CSV

Extract specific contact fields for external use:

```bash
kontakto serci --organization "MyOrg" | grep -oP "(?<=email: )\S+"
```

### Auto-Primary Assignment

Single phone/email are automatically primary, reducing input:

```bash
# Just type the number, it gets assigned "prima" automatically
kontakto aldoni -n "Quick Add" -t "+33123456789"
```

## Troubleshooting

### Contact Not Found

**Problem:** `kontakto vidi john@example.com` says contact not found.

**Solution:** 
- Check the exact email with `kontakto serci "john"`
- UUID must be quoted if it starts with `#`: `kontakto vidi "#12345678"`

### Duplicate Contact Detected

**Problem:** When adding a contact, autish asks about a duplicate.

**Solution:** Choose one of:
- **a** to update the existing entry
- **k** to keep both (create new)
- **N** to cancel

### Markdown Links Not Showing

**Problem:** Links in notes appear as plain text.

**Solution:**
- Check the UUIDs match existing encik/vorto entries
- Links render on display; invalid UUIDs are silently ignored
- Syntax must be `[text](ec#uuid)` or `[text](vt#uuid)`

## See Also

- [Autish README](../README.md) — Main documentation
- [Bash Alias](BASH_ALIAS.md) — Bash alias management
- [Encik](ENCIK.md) — Encyclopedia entries
- [Vorto](VORTO.md) — Word vocabulary
