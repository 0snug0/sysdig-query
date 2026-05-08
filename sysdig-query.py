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

_SAMPLE_QUERY = (
    "MATCH CloudResource AFFECTED_BY Vulnerability\n"
    " WHERE Vulnerability.severity = 'Critical'\n"
    " RETURN DISTINCT CloudResource, Vulnerability\n"
    " LIMIT 50;"
)

# Shared color-pair numbers (consistent across all screens)
#   1  BLACK / CYAN    selected row / highlight
#   2  CYAN  / default header, accent
#   3  GREEN / default success, status
#   4  BLACK / RED     danger (delete confirm)
#   5  BLACK / YELLOW  action-mode bar in editor


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


def save_result(result, uid):
    epoch = int(time.time())
    filename = f"sysdig-query-{uid}-{epoch}.json"
    filepath = os.path.join(os.getcwd(), filename)
    with open(filepath, "w") as f:
        json.dump(result, f, indent=2)
    return filepath


def save_favorite_query(token, base_url, query_text):
    """Raises RuntimeError on HTTP failure so callers decide how to surface it."""
    url = f"{base_url}/api/query-storage/v1/favorite-queries"
    payload = json.dumps({"query": query_text}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code} {e.reason}: {body}")


def delete_favorite_query(token, base_url, uuid):
    """Raises RuntimeError on HTTP failure."""
    url = f"{base_url}/api/query-storage/v1/favorite-queries/{uuid}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code} {e.reason}: {body}")


# ---------------------------------------------------------------------------
# curses helpers shared by multiple screens
# ---------------------------------------------------------------------------

def _init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK,  curses.COLOR_CYAN)
    curses.init_pair(2, curses.COLOR_CYAN,   -1)
    curses.init_pair(3, curses.COLOR_GREEN,  -1)
    curses.init_pair(4, curses.COLOR_BLACK,  curses.COLOR_RED)
    curses.init_pair(5, curses.COLOR_BLACK,  curses.COLOR_YELLOW)


def _reinit_picker(stdscr):
    """Restore picker state after returning from a sub-screen (editor / result viewer)."""
    _init_colors()
    curses.curs_set(0)
    stdscr.keypad(True)


def _run_and_show(stdscr, token, base_url, query_text, saved_uuid=None):
    """Run a SysQL query and display results in the scrollable viewer.
    Called directly (already inside curses) rather than via curses.wrapper."""
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    msg = " Running query… "
    stdscr.addstr(max_y // 2, max(0, (max_x - len(msg)) // 2), msg[:max_x])
    stdscr.refresh()

    result = run_query(token, base_url, query_text)
    result_text = json.dumps(result, indent=2)
    uid = saved_uuid or "adhoc"
    info = f"favorite: {saved_uuid}" if saved_uuid else None
    curses_result(stdscr, result_text, uid, info=info)


# ---------------------------------------------------------------------------
# SysQL query editor — edit phase then action phase
# ---------------------------------------------------------------------------

def curses_query_editor(stdscr, initial, token, base_url):
    """Two-phase SysQL query editor.

    Edit phase
      Shift+Enter / numpad Enter  →  insert new line
      Enter                       →  move to action phase
      Esc                         →  cancel (returns None action)

    Action phase
      s  save as favorite (stays in action phase, updates status bar)
      r  run query        (exits, returns action='run')
      e  back to edit
      q  quit             (exits, returns action=None)

    Returns (action, query_text, saved_uuid).
      action is 'run' or None.
    """
    _init_colors()
    curses.curs_set(1)
    stdscr.keypad(True)

    lines = initial.split("\n") if initial else [""]
    crow, ccol = len(lines) - 1, len(lines[-1])
    scroll = 0
    saved_uuid = None
    flash_msg = ""
    phase = "edit"

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        # ── header ────────────────────────────────────────────────────────
        if phase == "edit":
            hdr = " SysQL Editor  |  Shift+Enter: new line  |  Enter: done  |  Esc: cancel "
            stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
            stdscr.addstr(0, 0, hdr[:max_x])
            stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)
            curses.curs_set(1)
        else:
            hdr = " Query ready "
            stdscr.attron(curses.color_pair(5) | curses.A_BOLD)
            stdscr.addstr(0, 0, hdr[:max_x].ljust(max_x - 1))
            stdscr.attroff(curses.color_pair(5) | curses.A_BOLD)
            curses.curs_set(0)

        # ── query text ────────────────────────────────────────────────────
        edit_rows = max_y - 3
        if crow < scroll:
            scroll = crow
        elif crow >= scroll + edit_rows:
            scroll = crow - edit_rows + 1

        for i in range(edit_rows):
            li = scroll + i
            if li < len(lines):
                stdscr.addstr(1 + i, 0, lines[li][:max_x - 1])

        # ── status / action bar ───────────────────────────────────────────
        if flash_msg:
            stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
            stdscr.addstr(max_y - 1, 0, flash_msg[:max_x - 1])
            stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)
        elif phase == "edit":
            status = f" row {crow+1}/{len(lines)}  col {ccol+1}"
            if saved_uuid:
                status += f"  |  favorite: {saved_uuid}"
            stdscr.attron(curses.color_pair(2))
            stdscr.addstr(max_y - 1, 0, status[:max_x - 1])
            stdscr.attroff(curses.color_pair(2))
        else:
            if saved_uuid:
                bar = f" r: run   e: back to edit   q: quit   [saved: {saved_uuid}] "
            else:
                bar = " s: save favorite   r: run   e: back to edit   q: quit "
            stdscr.attron(curses.color_pair(5) | curses.A_BOLD)
            stdscr.addstr(max_y - 1, 0, bar[:max_x - 1].ljust(max_x - 1))
            stdscr.attroff(curses.color_pair(5) | curses.A_BOLD)

        # ── cursor (edit phase only) ──────────────────────────────────────
        if phase == "edit":
            try:
                stdscr.move(1 + crow - scroll, min(ccol, max_x - 1))
            except curses.error:
                pass

        stdscr.refresh()
        flash_msg = ""
        key = stdscr.getch()

        # ── edit phase key handling ───────────────────────────────────────
        if phase == "edit":
            line = lines[crow]

            if key in (10, 13):                      # Enter → action phase
                phase = "action"

            elif key == curses.KEY_ENTER:            # Shift+Enter / numpad → new line
                lines.insert(crow + 1, line[ccol:])
                lines[crow] = line[:ccol]
                crow += 1
                ccol = 0

            elif key == 27:                          # Esc → cancel
                return (None, None, saved_uuid)

            elif key == curses.KEY_UP:
                if crow > 0:
                    crow -= 1
                    ccol = min(ccol, len(lines[crow]))
            elif key == curses.KEY_DOWN:
                if crow < len(lines) - 1:
                    crow += 1
                    ccol = min(ccol, len(lines[crow]))
            elif key == curses.KEY_LEFT:
                if ccol > 0:
                    ccol -= 1
                elif crow > 0:
                    crow -= 1
                    ccol = len(lines[crow])
            elif key == curses.KEY_RIGHT:
                if ccol < len(line):
                    ccol += 1
                elif crow < len(lines) - 1:
                    crow += 1
                    ccol = 0
            elif key == curses.KEY_HOME:
                ccol = 0
            elif key == curses.KEY_END:
                ccol = len(line)
            elif key == curses.KEY_PPAGE:
                crow = max(0, crow - edit_rows)
                ccol = min(ccol, len(lines[crow]))
            elif key == curses.KEY_NPAGE:
                crow = min(len(lines) - 1, crow + edit_rows)
                ccol = min(ccol, len(lines[crow]))
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                if ccol > 0:
                    lines[crow] = line[:ccol - 1] + line[ccol:]
                    ccol -= 1
                elif crow > 0:
                    prev_len = len(lines[crow - 1])
                    lines[crow - 1] += line
                    lines.pop(crow)
                    crow -= 1
                    ccol = prev_len
            elif key == curses.KEY_DC:
                if ccol < len(line):
                    lines[crow] = line[:ccol] + line[ccol + 1:]
                elif crow < len(lines) - 1:
                    lines[crow] = line + lines[crow + 1]
                    lines.pop(crow + 1)
            elif 32 <= key < 256:                    # printable ASCII
                lines[crow] = line[:ccol] + chr(key) + line[ccol:]
                ccol += 1

        # ── action phase key handling ─────────────────────────────────────
        else:
            qt = "\n".join(lines).strip()

            if key in (ord("s"), ord("S")):
                if not qt:
                    flash_msg = " Cannot save an empty query "
                elif saved_uuid:
                    flash_msg = f" Already saved as favorite: {saved_uuid} "
                else:
                    try:
                        resp = save_favorite_query(token, base_url, qt)
                        saved_uuid = resp.get("uuid", "saved")
                        return (None, qt, saved_uuid)
                    except RuntimeError as e:
                        flash_msg = f" Save failed: {e} "

            elif key in (ord("r"), ord("R")):
                if not qt:
                    flash_msg = " Cannot run an empty query "
                else:
                    return ("run", qt, saved_uuid)

            elif key in (ord("e"), ord("E"), 27):    # back to edit
                phase = "edit"

            elif key in (ord("q"), ord("Q")):
                return (None, "\n".join(lines), saved_uuid)


# ---------------------------------------------------------------------------
# curses picker — navigate / run / edit / new / delete
# ---------------------------------------------------------------------------

def curses_picker(stdscr, favorites, token, base_url):
    _init_colors()
    curses.curs_set(0)
    stdscr.keypad(True)

    selected = 0
    scroll_offset = 0
    confirm_delete = False
    status_msg = ""

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        hdr = (" Sysdig Favorite Queries  |  "
               "ENTER: run  |  e: edit  |  n: new  |  d: delete  |  q: quit ")
        stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
        stdscr.addstr(0, 0, hdr[:max_x])
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
                stdscr.addstr(screen_row, 0, row_text[:max_x])

        div_row = max_y - 4
        stdscr.attron(curses.color_pair(2))
        stdscr.addstr(div_row, 0, "─" * (max_x - 1))
        stdscr.attroff(curses.color_pair(2))

        fav = favorites[selected]
        if confirm_delete:
            prompt = f" Delete [{fav['uuid']}]?  y = confirm  any other key = cancel "
            stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
            stdscr.addstr(div_row + 1, 0, prompt[:max_x].ljust(max_x - 1))
            stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
        elif status_msg:
            stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
            stdscr.addstr(div_row + 1, 0, status_msg[:max_x])
            stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)
        else:
            preview_lines = fav["query"].strip().split("\n")
            stdscr.attron(curses.A_DIM)
            for li, line in enumerate(preview_lines[:3]):
                stdscr.addstr(div_row + 1 + li, 2, line[:max_x - 3])
            stdscr.attroff(curses.A_DIM)

        stdscr.refresh()
        key = stdscr.getch()

        # ── delete confirmation ───────────────────────────────────────────
        if confirm_delete:
            confirm_delete = False
            if key == ord("y"):
                uuid_to_delete = favorites[selected]["uuid"]
                try:
                    delete_favorite_query(token, base_url, uuid_to_delete)
                    favorites.pop(selected)
                    if not favorites:
                        return None
                    selected = min(selected, len(favorites) - 1)
                    status_msg = f" Deleted {uuid_to_delete} "
                except RuntimeError as e:
                    status_msg = f" Delete failed: {e} "
            continue

        status_msg = ""

        # ── navigation ────────────────────────────────────────────────────
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

        # ── run selected favorite ─────────────────────────────────────────
        elif key in (10, 13, curses.KEY_ENTER):
            return favorites[selected]

        # ── edit selected favorite ────────────────────────────────────────
        elif key == ord("e"):
            action, qt, uid = curses_query_editor(
                stdscr, favorites[selected]["query"], token, base_url
            )
            _reinit_picker(stdscr)
            if action == "run" and qt:
                _run_and_show(stdscr, token, base_url, qt, uid)
                _reinit_picker(stdscr)
            if uid:
                favorites[:] = fetch_favorites(token, base_url)
                if not favorites:
                    return None
                selected = min(selected, len(favorites) - 1)

        # ── new query ─────────────────────────────────────────────────────
        elif key == ord("n"):
            action, qt, uid = curses_query_editor(stdscr, "", token, base_url)
            _reinit_picker(stdscr)
            if action == "run" and qt:
                _run_and_show(stdscr, token, base_url, qt, uid)
                _reinit_picker(stdscr)
            if uid:
                favorites[:] = fetch_favorites(token, base_url)
                if not favorites:
                    return None
                selected = min(selected, len(favorites) - 1)

        # ── delete ────────────────────────────────────────────────────────
        elif key == ord("d"):
            confirm_delete = True
        elif key == ord("D"):
            uuid_to_delete = favorites[selected]["uuid"]
            try:
                delete_favorite_query(token, base_url, uuid_to_delete)
                favorites.pop(selected)
                if not favorites:
                    return None
                selected = min(selected, len(favorites) - 1)
                status_msg = f" Deleted {uuid_to_delete} "
            except RuntimeError as e:
                status_msg = f" Delete failed: {e} "

        elif key in (ord("q"), ord("Q"), 27):
            return None


# ---------------------------------------------------------------------------
# post-run result screen
# ---------------------------------------------------------------------------

def curses_result(stdscr, result_text, uuid, saved_path=None, info=None):
    """Scrollable result viewer. s = save to file, q/Esc = back."""
    _init_colors()
    curses.curs_set(0)

    lines = result_text.split("\n")
    scroll = 0

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        header = " Query Result  |  UP/DOWN: scroll  |  s: save to file  |  q: back "
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
            status += f"  |  file: {saved_path}"
        if info:
            status += f"  |  {info}"
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
# main interactive flow (favorites picker)
# ---------------------------------------------------------------------------

def interactive_mode(token, base_url):
    favorites = fetch_favorites(token, base_url)
    if not favorites:
        print("No favorite queries found.")
        return

    while True:
        selected = curses.wrapper(curses_picker, favorites, token, base_url)

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
