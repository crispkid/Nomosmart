"""Private, fixed local DOCX child launcher; no OS isolation claim."""
import os
import resource
import sys


def main():
    memory, cpu, output = map(int, sys.argv[1:4])
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (output, output))
    os.execve(sys.argv[4], sys.argv[4:], dict(os.environ))


if __name__ == "__main__":
    main()
