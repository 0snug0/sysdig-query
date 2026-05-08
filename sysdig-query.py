#!/usr/bin/env python3

import os
import sys
import json
import time
import curses
import argparse
import urllib.request
import urllib.parse
import urllib.error

# Region reference: https://docs.sysdig.com/en/administration/saas-regions-and-ip-ranges/
REGIONS = {
    "US East (North Virginia)":      "https://secure.sysdig.com",
    "US West (Oregon)":              "https://us2.app.sysdig.com",
    "US West (GCP)":                 "https://app.us4.sysdig.com",
    "EU Central (Frankfurt)":        "https://eu1.app.sysdig.com",
    "EU North (Stockholm)":          "https://app.eu2.sysdig.com",
    "Asia Pacific (Sydney)":         "https://app.au1.sysdig.com",
    "Middle East / Dammam (GCP)":    "https://app.me2.sysdig.com",
    "Asia Pacific South (Mumbai)":   "https://app.in1.sysdig.com",
    "Asia Pacific Japan (Tokyo)":    "https://app.jp1.sysdig.com",
}


def get_token():
    token = os.environ.get("SDC_SECURE_TOKEN")
    if not token:
        print("ERROR: SDC_SECURE_TOKEN environment variable is not set.")
        sys.exit(1)
    return token


def get_base_url():
    url = os.environ.get("SDC_SECURE_URL", "").rstrip("/")
    if not url:
        print("ERROR: SDC_SECURE_URL environment variable is not set.")
        print()
        print("Set it to the base URL for your Sysdig region:")
        print()
        max_name = max(len(k) for k in REGIONS)
        for name, base in REGIONS.items():
            print(f"  {name:<{max_name}}  {base}")
        print()
        print("Example:")
        print("  export SDC_SECURE_URL=https://secure.sysdig.com       # US East")
        print("  export SDC_SECURE_URL=https://us2.app.sysdig.com      # US West")
        print("  export SDC_SECURE_URL=https://app.me2.sysdig.com      # Middle East")
        sys.exit(1)
    return url


def fetch_favorites(token, base_url):
    url = f"{base_url}/api/query-storage/v1/favorite-queries"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"ERROR: HTTP {e.code} fetching favorites from {url}: {e.reason}")
        sys.exit(1)


def run_query(token, base_url, query_text):
    params = urllib.parse.urlencode({"q": query_text})
    url = f"{base_url}/api/sysql/v2/query?{params}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"ERROR: HTTP {e.code} running query: {e.reason}")
        print(body)
        sys.exit(1)


def save_result(result, uuid):
    epoch = int(time.time())
    filename = f"sysdig-query-{uuid}-{epoch}.json"
    filepath = os.path.join(os.getcwd(), filename)
    with open(filepath, "w") as f:
        json.dump(result, f, indent=2)
    return filepath


# ---------------------------------------------------------------------------
# curses picker — navigate with arrows, Enter to select, q to quit
# ---------------------------------------------------------------------------

def curses_picker(stdscr, favorites):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)   # selected row
    curses.init_pair(2, curses.COLOR_CYAN,  -1)                  # header / accent
    curses.init_pair(3, curses.COLOR_WHITE, -1)                  # normal row

    selected = 0
    scroll_offset = 0

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        header = " Sysdig Favorite Queries  |  UP/DOWN: navigate  |  ENTER: run  |  q: quit "
        stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
        stdscr.addstr(0, 0, header[:max_x])
        stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)

        col_header = f"  {'#':<4} {'UUID':<38} {'Query preview'}"
        stdscr.attron(curses.A_UNDERLINE)
        stdscr.addstr(1, 0, col_header[:max_x])
        stdscr.attroff(curses.A_UNDERLINE)

        list_rows = max_y - 7
        if list_rows < 1:
            list_rows = 1

        if selected < scroll_offset:
            scroll_offset = selected
        elif selected >= scroll_offset + list_rows:
            scroll_offset = selected - list_rows + 1

        for i in range(list_rows):
            idx = scroll_offset + i
            if idx >= len(favorites):
                break
            fav = favorites[idx]
            preview = fav["query"].replace("\n", " ").strip()
            max_preview = max_x - 46
            if len(preview) > max_preview:
                preview = preview[:max_preview - 3] + "..."
            row_text = f"  {idx+1:<4} {fav['uuid']:<38} {preview}"

            screen_row = 2 + i
            if idx == selected:
                stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
                stdscr.addstr(screen_row, 0, row_text[:max_x].ljust(max_x - 1))
                stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
            else:
                stdscr.attron(curses.color_pair(3))
                stdscr.addstr(screen_row, 0, row_text[:max_x])
                stdscr.attroff(curses.color_pair(3))

        div_row = max_y - 4
        stdscr.attron(curses.color_pair(2))
        stdscr.addstr(div_row, 0, "─" * (max_x - 1))
        stdscr.attroff(curses.color_pair(2))

        fav = favorites[selected]
        preview_lines = fav["query"].strip().split("\n")
        stdscr.attron(curses.A_DIM)
        for li, line in enumerate(preview_lines[:3]):
            stdscr.addstr(div_row + 1 + li, 2, line[:max_x - 3])
        stdscr.attroff(curses.A_DIM)

        stdscr.refresh()

        key = stdscr.getch()

        if key in (curses.KEY_UP, ord("k")):
            selected = max(0, selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = min(len(favorites) - 1, selected + 1)
        elif key == curses.KEY_PPAGE:
            selected = max(0, selected - list_rows)
        elif key == curses.KEY_NPAGE:
            selected = min(len(favorites) - 1, selected + list_rows)
        elif key == curses.KEY_HOME:
            selected = 0
        elif key == curses.KEY_END:
            selected = len(favorites) - 1
        elif key in (10, 13, curses.KEY_ENTER):
            return favorites[selected]
        elif key in (ord("q"), ord("Q"), 27):
            return None


# ---------------------------------------------------------------------------
# post-run result screen inside curses
# ---------------------------------------------------------------------------

def curses_result(stdscr, result_text, uuid):
    """Scrollable result viewer. s = save, q/Esc = back."""
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(2, curses.COLOR_CYAN,  -1)
    curses.init_pair(3, curses.COLOR_GREEN, -1)

    lines = result_text.split("\n")
    scroll = 0
    saved_path = None

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        header = " Query Result  |  UP/DOWN: scroll  |  s: save to file  |  q: back to list "
        stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
        stdscr.addstr(0, 0, header[:max_x])
        stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)

        view_rows = max_y - 2
        for i in range(view_rows):
            li = scroll + i
            if li >= len(lines):
                break
            stdscr.addstr(1 + i, 0, lines[li][:max_x - 1])

        status = f" line {scroll+1}/{len(lines)}"
        if saved_path:
            status += f"  |  saved: {saved_path}"
        stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
        stdscr.addstr(max_y - 1, 0, status[:max_x - 1])
        stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)

        stdscr.refresh()

        key = stdscr.getch()

        if key in (curses.KEY_UP, ord("k")):
            scroll = max(0, scroll - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            scroll = min(max(0, len(lines) - view_rows), scroll + 1)
        elif key == curses.KEY_PPAGE:
            scroll = max(0, scroll - view_rows)
        elif key == curses.KEY_NPAGE:
            scroll = min(max(0, len(lines) - view_rows), scroll + view_rows)
        elif key in (ord("s"), ord("S")) and not saved_path:
            result_obj = json.loads(result_text)
            saved_path = save_result(result_obj, uuid)
        elif key in (ord("q"), ord("Q"), 27, ord("b")):
            return


# ---------------------------------------------------------------------------
# main interactive flow
# ---------------------------------------------------------------------------

def interactive_mode(token, base_url):
    favorites = fetch_favorites(token, base_url)
    if not favorites:
        print("No favorite queries found.")
        return

    while True:
        selected = curses.wrapper(curses_picker, favorites)

        if selected is None:
            print("Bye.")
            break

        uuid = selected["uuid"]
        query = selected["query"]

        print(f"\nRunning query [{uuid}]...")
        result = run_query(token, base_url, query)
        result_text = json.dumps(result, indent=2)

        curses.wrapper(curses_result, result_text, uuid)


# ---------------------------------------------------------------------------
# non-interactive helpers
# ---------------------------------------------------------------------------

def cmd_list(token, base_url):
    favorites = fetch_favorites(token, base_url)
    if not favorites:
        print("No favorite queries found.")
        return
    print()
    print(f"{'#':<4} {'UUID':<38} {'Preview'}")
    print("-" * 90)
    for i, fav in enumerate(favorites, 1):
        preview = fav["query"].replace("\n", " ").strip()
        if len(preview) > 46:
            preview = preview[:43] + "..."
        print(f"{i:<4} {fav['uuid']:<38} {preview}")
    print()


def cmd_run(token, base_url, uuid, save=False):
    favorites = fetch_favorites(token, base_url)
    match = next((f for f in favorites if f["uuid"] == uuid), None)
    if not match:
        print(f"ERROR: No favorite query found with uuid: {uuid}")
        sys.exit(1)

    print(f"Running query: {match['query'].strip()}\n")
    result = run_query(token, base_url, match["query"])
    print(json.dumps(result, indent=2))

    if save:
        filepath = save_result(result, uuid)
        print(f"\nSaved to: {filepath}")


def cmd_regions():
    print()
    print(f"{'Region':<35} {'SDC_SECURE_URL'}")
    print("-" * 75)
    for name, url in REGIONS.items():
        print(f"{name:<35} {url}")
    print()


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sysdig favorite query runner. Run without args for interactive mode.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list", help="List all favorite queries")
    subparsers.add_parser("regions", help="List all supported regions and their URLs")

    run_parser = subparsers.add_parser("run", help="Run a favorite query by UUID")
    run_parser.add_argument("uuid", help="UUID of the favorite query")
    run_parser.add_argument(
        "--save", "-s",
        action="store_true",
        help="Save output to sysdig-query-<uuid>-<epoch>.json in cwd"
    )

    if len(sys.argv) == 1:
        token = get_token()
        base_url = get_base_url()
        interactive_mode(token, base_url)
        return

    args = parser.parse_args()

    if args.command == "regions":
        cmd_regions()
        return

    token = get_token()
    base_url = get_base_url()

    if args.command == "list":
        cmd_list(token, base_url)
    elif args.command == "run":
        cmd_run(token, base_url, args.uuid, save=args.save)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
