"""`relayout` command: talk to the running daemon.

    relayout status | flip | subscribe
    relayout auto on|off|toggle
    relayout exclude add|rm CLASS | list
    relayout rules list | add WORD [LAYOUT] | keep WORD | rm WORD
    relayout --stdin        read the command line from stdin (keeps words that
                            may be private out of the process arguments)
"""
import socket
import sys

from relayout.control import socket_path

USAGE = __doc__


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    if args == ["--stdin"]:
        line = sys.stdin.readline(4096).strip()
    else:
        line = " ".join(args)
    if "\n" in line:
        print("error: newline in arguments", file=sys.stderr)
        return 2
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(str(socket_path()))
    except OSError:
        print("relayout daemon is not running", file=sys.stderr)
        return 1
    s.sendall((line + "\n").encode())
    f = s.makefile("r", encoding="utf-8")
    try:
        for reply in f:
            print(reply.rstrip("\n"), flush=True)
            if reply.startswith("error:"):
                return 1
    except KeyboardInterrupt:
        pass
    except BrokenPipeError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
