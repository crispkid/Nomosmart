"""Private child launcher: fixed argv, no shell or inherited secrets.

No network/UID/memory sandbox is promised. This wrapper sets only a file-size
ceiling and disables core dumps before replacing itself with the configured tool.
"""
import os
import resource
import sys


def main():
    maximum = int(sys.argv[1])
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (maximum, maximum))
    os.execve(sys.argv[2], sys.argv[2:], dict(os.environ))


if __name__ == "__main__":
    main()
