#!/usr/bin/env python3

import argparse
import json
import threading
import time

import requests
import websocket

# ------------------------------------------------------------
# STATE
# ------------------------------------------------------------


class PageCounter:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests = {}

    def reset(self):
        with self.lock:
            self.requests.clear()

    def add(self, request_id, data):
        if not request_id:
            return

        with self.lock:
            if request_id not in self.requests:
                self.requests[request_id] = data
            else:
                self.requests[request_id].update(data)

    def snapshot(self):
        with self.lock:
            return dict(self.requests)


counter = PageCounter()

load_event = threading.Event()
stop_event = threading.Event()

last_load_time = time.monotonic()
last_load_lock = threading.Lock()


# ------------------------------------------------------------
# CDP
# ------------------------------------------------------------


def get_ws_url():
    tabs = requests.get(
        "http://localhost:9222/json",
        timeout=5,
    ).json()

    for tab in tabs:
        if tab.get("type") == "page":
            return tab["webSocketDebuggerUrl"]

    raise RuntimeError("No Chrome page tab found")


def connect():

    ws = websocket.create_connection(
        get_ws_url(),
        timeout=5,
    )

    ws.settimeout(5)

    commands = [
        {
            "id": 1,
            "method": "Network.enable",
        },
        {
            "id": 2,
            "method": "Network.setCacheDisabled",
            "params": {
                "cacheDisabled": True,
            },
        },
        {
            "id": 3,
            "method": "Network.setBypassServiceWorker",
            "params": {
                "bypass": True,
            },
        },
        {
            "id": 4,
            "method": "Page.enable",
        },
    ]

    for command in commands:
        ws.send(json.dumps(command))

    return ws


# ------------------------------------------------------------
# EVENT READER
# ------------------------------------------------------------


def reader(ws):

    global last_load_time

    print("[CDP] reader started")

    while not stop_event.is_set():
        try:
            raw = ws.recv()

            if not raw:
                continue

            message = json.loads(raw)

        except websocket.WebSocketTimeoutException:
            continue

        except websocket.WebSocketConnectionClosedException:
            print("[CDP] websocket closed")
            return

        except Exception as e:
            print(f"[CDP] reader stopped: {e}")
            return

        method = message.get("method")
        params = message.get(
            "params",
            {},
        )

        if method == "Page.loadEventFired":
            with last_load_lock:
                last_load_time = time.monotonic()

            load_event.set()

        elif method == "Network.responseReceived":
            request_id = params.get("requestId")

            response = params.get(
                "response",
                {},
            )

            counter.add(
                request_id,
                {
                    "url": response.get("url"),
                    "status": response.get("status"),
                    "bytes": 0,
                },
            )

        elif method == "Network.loadingFinished":
            request_id = params.get("requestId")

            counter.add(
                request_id,
                {
                    "bytes": params.get(
                        "encodedDataLength",
                        0,
                    )
                },
            )


# ------------------------------------------------------------
# SAVE RESULT
# ------------------------------------------------------------


def make_entry(index):

    snapshot = counter.snapshot()

    total = 0
    requests_out = []

    for request_id, data in snapshot.items():
        size = data.get(
            "bytes",
            0,
        )

        total += size

        requests_out.append(
            {
                "request_id": request_id,
                "url": data.get("url"),
                "status": data.get("status"),
                "bytes": size,
            }
        )

    return {
        "load_index": index,
        "total_bytes": total,
        "request_count": len(snapshot),
        "requests": requests_out,
    }


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--out",
        required=True,
    )

    parser.add_argument(
        "--measurements",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Maximum wait for a reload",
    )

    parser.add_argument(
        "--settle",
        type=int,
        default=2,
        help="Wait after load before snapshot",
    )

    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=20,
        help="Stop after no reload events",
    )

    args = parser.parse_args()

    ws = connect()

    thread = threading.Thread(
        target=reader,
        args=(ws,),
        daemon=True,
    )

    thread.start()

    # --------------------------------------------------------
    # IGNORE INITIAL SETUP LOAD
    # --------------------------------------------------------

    print("[CDP] waiting for setup load...")

    load_event.clear()

    if load_event.wait(args.timeout):
        print("[CDP] setup load ignored")
    else:
        print("[CDP] no setup load seen")

    counter.reset()

    # --------------------------------------------------------
    # MEASUREMENTS
    # --------------------------------------------------------

    print("[CDP] starting measurements")

    with open(
        args.out,
        "w",
        buffering=1,
    ) as output:
        output.write("[\n")

        written = 0

        for index in range(
            1,
            args.measurements + 1,
        ):
            with last_load_lock:
                idle = time.monotonic() - last_load_time

            if idle > args.idle_timeout:
                print(f"[CDP] no reload for {args.idle_timeout}s, stopping")

                break

            counter.reset()
            load_event.clear()

            print(f"[CDP] waiting for load {index}/{args.measurements}")

            if not load_event.wait(args.timeout):
                print(f"[CDP] timeout waiting for load {index}")

                break

            time.sleep(args.settle)

            entry = make_entry(index)

            if written:
                output.write(",\n")

            json.dump(
                entry,
                output,
                indent=2,
            )

            output.flush()

            written += 1

            print(
                f"[CDP] {index}: "
                f"{entry['total_bytes']} bytes "
                f"({entry['request_count']} requests)"
            )

        output.write("\n]\n")

    stop_event.set()

    try:
        ws.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
