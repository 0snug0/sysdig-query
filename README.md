# sysdig-query

A terminal UI for browsing, running, creating, editing, and deleting your Sysdig
favorite SysQL queries. Everything is done interactively — no query text needed on
the command line.

## Requirements

- Python 3.6+
- No third-party dependencies (stdlib only: `curses`, `urllib`, `json`)
- A valid Sysdig API token and your region base URL

## Setup

Export your credentials before running:

```bash
export SDC_SECURE_TOKEN=your_token_here
export SDC_SECURE_URL=https://secure.sysdig.com   # change to match your region
```

Make the script executable (one-time):

```bash
chmod +x sysdig-query.py
```

## Regions

| Region                        | SDC_SECURE_URL                    |
|-------------------------------|-----------------------------------|
| US East (North Virginia)      | https://secure.sysdig.com         |
| US West (Oregon)              | https://us2.app.sysdig.com        |
| US West (GCP)                 | https://app.us4.sysdig.com        |
| EU Central (Frankfurt)        | https://eu1.app.sysdig.com        |
| EU North (Stockholm)          | https://app.eu2.sysdig.com        |
| Asia Pacific (Sydney)         | https://app.au1.sysdig.com        |
| Middle East / Dammam (GCP)    | https://app.me2.sysdig.com        |
| Asia Pacific South (Mumbai)   | https://app.in1.sysdig.com        |
| Asia Pacific Japan (Tokyo)    | https://app.jp1.sysdig.com        |

```bash
python3 sysdig-query.py regions   # print this table
```

Reference: https://docs.sysdig.com/en/administration/saas-regions-and-ip-ranges/

---

## Interactive mode

Run with no arguments to launch the full TUI:

```bash
python3 sysdig-query.py
```

### Favorites picker

The picker lists all your saved favorite queries. A preview pane at the bottom
shows the full query text for the highlighted row.

| Key         | Action                              |
|-------------|-------------------------------------|
| UP / DOWN   | Navigate the list                   |
| k / j       | Navigate (vim-style)                |
| PgUp / PgDn | Jump a full page                    |
| Home / End  | Jump to first / last entry          |
| ENTER       | Run the highlighted query           |
| e           | Edit the highlighted query          |
| n           | New query                           |
| d           | Delete (asks for confirmation)      |
| D           | Delete immediately (no confirmation)|
| q / Escape  | Quit                                |

### Query editor

Pressing **e** or **n** opens the two-phase SysQL editor.

**Edit phase** — write your query:

| Key                      | Action             |
|--------------------------|--------------------|
| Type normally            | Insert text        |
| Shift+Enter / numpad Enter | Insert new line  |
| Arrow keys               | Move cursor        |
| Backspace / Delete       | Delete characters  |
| PgUp / PgDn              | Scroll editor      |
| Enter                    | Finish — go to action phase |
| Esc                      | Cancel             |

**Action phase** — choose what to do with the query (yellow bar at the bottom):

| Key | Action                                                    |
|-----|-----------------------------------------------------------|
| s   | Save as favorite → returns to the favorites list          |
| r   | Run the query → opens the result viewer                   |
| e   | Back to edit phase                                        |
| q   | Quit to favorites list (discards unsaved changes)         |

You can save first (`s`) and then come back and run (`r`) in the same session.

### Result viewer

| Key         | Action                      |
|-------------|-----------------------------|
| UP / DOWN   | Scroll JSON output          |
| k / j       | Scroll (vim-style)          |
| PgUp / PgDn | Scroll by page              |
| s           | Save output to file in cwd  |
| q / Escape  | Back                        |

Saved output files are named `sysdig-query-<uuid>-<epoch>.json`.

---

## Non-interactive commands

### List all saved queries

```bash
python3 sysdig-query.py list
```

Prints a table of all favorite queries with UUID and a query preview.

### Run a query by UUID

```bash
python3 sysdig-query.py run <uuid>
python3 sysdig-query.py run <uuid> --save   # also write result to file
```

Prints JSON to stdout. `--save` writes `sysdig-query-<uuid>-<epoch>.json` to the
current directory.

---

## API endpoints used

| Method | Path                                                              | Purpose              |
|--------|-------------------------------------------------------------------|----------------------|
| GET    | `/api/query-storage/v1/favorite-queries`                          | Fetch all favorites  |
| POST   | `/api/query-storage/v1/favorite-queries`                          | Save new favorite    |
| DELETE | `/api/query-storage/v1/favorite-queries/{uuid}`                   | Delete a favorite    |
| GET    | `/api/sysql/v2/query?q=<query>`                                   | Run a SysQL query    |
