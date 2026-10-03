/* Wireless Wire launcher. Uses the operating system's C library and Python. */
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif

int main(int argc, char **argv) {
    char executable[PATH_MAX];
    char resolved[PATH_MAX];
#ifdef __APPLE__
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0) {
        fputs("wireless-wire: executable path is too long\n", stderr);
        return 1;
    }
#elif defined(__linux__)
    ssize_t size = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
    if (size < 0 || size >= (ssize_t)sizeof(executable) - 1) {
        fputs("wireless-wire: cannot locate executable\n", stderr);
        return 1;
    }
    executable[size] = '\0';
#else
#error Unsupported platform
#endif
    if (!realpath(executable, resolved)) {
        fputs("wireless-wire: cannot resolve executable path\n", stderr);
        return 1;
    }
    char *slash = strrchr(resolved, '/');
    if (!slash) return 1;
    *slash = '\0';
    char app[PATH_MAX];
    int length = snprintf(app, sizeof(app), "%s/wireless-wire.pyz", resolved);
    if (length < 0 || (size_t)length >= sizeof(app) || access(app, R_OK) != 0) {
        fputs("wireless-wire: keep wireless-wire.pyz beside this executable\n", stderr);
        return 1;
    }
    const char *python = getenv("WIRELESS_WIRE_PYTHON");
    if (!python || !*python) python = "python3";
    char **args = calloc((size_t)argc + 2, sizeof(*args));
    if (!args) return 1;
    args[0] = (char *)python;
    args[1] = app;
    for (int i = 1; i < argc; ++i) args[i + 1] = argv[i];
    execvp(python, args);
    fprintf(stderr, "wireless-wire: Python 3.11+ is required (%s)\n", strerror(errno));
    free(args);
    return 1;
}
