"""Create-only physical-lock provisioning; no configuration, Docker or mail I/O."""

import json
import sys

if __package__:
    from .physical_lock import prepare
    from .private_env import PRIVATE
else:
    from physical_lock import prepare
    from private_env import PRIVATE


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise ValueError
        prepare(PRIVATE)
    except Exception:
        print(json.dumps({"status": "unavailable", "detail": "mail_lock_not_prepared"}))
        return 1
    print(json.dumps({"status": "ready"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
