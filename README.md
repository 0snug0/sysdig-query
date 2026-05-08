# sysdig-query

A CLI tool to browse and run your saved Sysdig favorite queries interactively
or via command line arguments.

## Requirements

- Python 3.6+
- No third-party dependencies (stdlib only: curses, urllib, json)
- A valid Sysdig API token and your region base URL

## Setup

Export your credentials before running:

```bash
export SDC_SECURE_TOKEN=your_token_here
export SDC_SECURE_URL=https://secure.sysdig.com   # change to match your region
```

Make the script executable (one-time):

```bash
chmod +x ~/Work/sysdig-query/sysdig-query.py
```

## Regions

Set SDC_SECURE_URL to the base URL for your region:

| Region                        | SDC_SECURE_URL                       |
|-------------------------------|--------------------------------------|
| US East (North Virginia)      | https://secure.sysdig.com            |
| US West (Oregon)              | https://us2.app.sysdig.com           |
| US West (GCP)                 | https://app.us4.sysdig.com           |
| EU Central (Frankfurt)        | https://eu1.app.sysdig.com           |
| EU North (Stockholm)          | https://app.eu2.sysdig.com           |
| Asia Pacific (Sydney)         | https://app.au1.sysdig.com           |
| Middle East / Dammam (GCP)    | https://app.me2.sysdig.com           |
| Asia Pacific South (Mumbai)   | https://app.in1.sysdig.com           |
| Asia Pacific Japan (Tokyo)    | https://app.jp1.sysdig.com           |

You can also run `python3 sysdig-query.py regions` to print this table at any time.

Reference: https://docs.sysdig.com/en/administration/saas-regions-and-ip-ranges/

## Usage

### Interactive mode

Run with no arguments to launch the full TUI:

```bash
python3 sysdig-query.py
```

**Picker screen:**

| Key            | Action                        |
|----------------|-------------------------------|
| UP / DOWN      | Move through queries          |
| k / j          | Move through queries (vim)    |
| PgUp / PgDn    | Jump a full page              |
| Home / End     | Jump to first / last          |
| ENTER          | Run the highlighted query     |
| q or Escape    | Quit                          |

A preview pane at the bottom shows the full query text for the highlighted row
before you run it.

**Result screen:**

| Key            | Action                              |
|----------------|-------------------------------------|
| UP / DOWN      | Scroll JSON output                  |
| k / j          | Scroll JSON output (vim)            |
| PgUp / PgDn    | Scroll by page                      |
| s              | Save output to file in cwd          |
| q or Escape    | Back to query list                  |

Saved files are named: `sysdig-query-<uuid>-<epoch>.json`

After viewing results you return to the picker automatically so you can run
multiple queries in one session.

---

### List all saved queries

```bash
python3 sysdig-query.py list
```

Prints a table of all your favorite queries with their UUID and a preview of
the query text.

---

### Run a query by UUID

```bash
python3 sysdig-query.py run <uuid>
```

Prints the JSON result to stdout.

**Auto-save output to file:**

```bash
python3 sysdig-query.py run <uuid> --save
```

Saves the result to `sysdig-query-<uuid>-<epoch>.json` in the current working
directory.

---

### List supported regions

```bash
python3 sysdig-query.py regions
```

Prints all supported regions and their corresponding SDC_SECURE_URL values.

---

## API Endpoints Used

| Purpose          | Path                                              |
|------------------|---------------------------------------------------|
| Favorite queries | GET {SDC_SECURE_URL}/api/query-storage/v1/favorite-queries |
| Run a query      | GET {SDC_SECURE_URL}/api/sysql/v2/query?q=<query> |

## File Structure

```
sysdig-query/
├── README.md
└── sysdig-query.py
```
