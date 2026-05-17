"""
Quick Vport attribute inspector.

Usage:
    python inspect_vport.py <ixnetwork_host> <username> <password> [--port 443]

Connects to IxNetwork, finds sessions that use chassis 10.36.65.163,
and dumps ALL attributes of the first matching Vport object.
"""

import argparse
import sys

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("host", help="IxNetwork Linux API Server IP/hostname")
    parser.add_argument("username")
    parser.add_argument("password")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--chassis", default="10.36.65.163", help="Chassis IP to filter ports")
    args = parser.parse_args()

    try:
        from ixnetwork_restpy.testplatform.testplatform import TestPlatform
    except ImportError:
        print("ERROR: ixnetwork_restpy not installed. pip install ixnetwork-restpy", file=sys.stderr)
        sys.exit(1)

    kwargs = {"ip_address": args.host, "verify_cert": False}
    if args.port:
        kwargs["rest_port"] = args.port

    print(f"Connecting to {args.host} ...")
    platform = TestPlatform(**kwargs)
    platform.Authenticate(args.username, args.password)
    print("Authenticated.\n")

    sessions = platform.Sessions.find()
    print(f"Found {len(sessions)} session(s).\n")

    for sess in sessions:
        try:
            vports = sess.Ixnetwork.Vport.find()
        except Exception as e:
            print(f"  Session {sess.Id}: failed to fetch vports — {e}")
            continue

        for vp in vports:
            location = str(getattr(vp, "Location", "") or "")
            assigned = str(getattr(vp, "AssignedTo", "") or "")

            if args.chassis not in location and args.chassis not in assigned:
                continue

            print(f"=== Session {sess.Id!r} | Vport: {getattr(vp, 'Name', '?')} ===")
            print(f"  Location   : {location}")
            print(f"  AssignedTo : {assigned}")
            print()
            print("  All attributes:")

            # Dump every attribute on the object
            for attr in sorted(dir(vp)):
                if attr.startswith("_"):
                    continue
                try:
                    val = getattr(vp, attr)
                    if callable(val):
                        continue
                    print(f"    {attr:40s} = {val!r}")
                except Exception:
                    pass

            print()
            print("  (Stopping after first matching vport — remove break to see all)")
            return  # show just the first match


if __name__ == "__main__":
    main()
