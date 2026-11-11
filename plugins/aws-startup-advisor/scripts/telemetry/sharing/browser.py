"""Launch the user's configured browser in a private, bounded parent process."""

import sys
import webbrowser


def main():
    try:
        return 0 if len(sys.argv) == 2 and webbrowser.open(sys.argv[1]) else 1
    except BaseException:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
