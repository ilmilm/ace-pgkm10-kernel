#!/usr/bin/env python3
"""Insert SukiSU-Ultra `builtin` manual hooks into a 5.10 kernel tree.

The builtin branch does NOT register kprobes/tracepoints; it expects the kernel
source to call its hook entry points.  Without these calls SukiSU still answers
supercalls (the manager shows "working" and a version), but execve is never
intercepted, so `su`/the manager never escalate and ksud is never installed.

Patches mirror https://sukisu.org/zh/guide/how-to-integrate (5.10 column).
Every anchor is mandatory: if a function is missing we abort instead of
silently producing a kernel without hooks.
"""
import sys

EXEC = """#ifdef CONFIG_KSU
	{
		extern int ksu_handle_execveat(int *, struct filename **, void *, void *, int *);
		ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);
	}
#endif
"""

FACCESSAT = """#ifdef CONFIG_KSU
	{
		extern int ksu_handle_faccessat(int *, const char __user **, int *, int *);
		ksu_handle_faccessat(&dfd, &filename, &mode, NULL);
	}
#endif
"""

STAT = """#ifdef CONFIG_KSU
	{
		extern int ksu_handle_stat(int *, const char __user **, int *);
		ksu_handle_stat(&dfd, &filename, &flag);
	}
#endif
"""

REBOOT = """#ifdef CONFIG_KSU
	{
		extern int ksu_handle_sys_reboot(int, int, unsigned int, void __user **);
		ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);
	}
#endif
"""

# (file, function-signature-anchor, insert-before-anchor, payload, label)
JOBS = [
    ("fs/exec.c",
     "static int do_execveat_common(int fd, struct filename *filename,",
     "\tif (IS_ERR(filename))",
     EXEC, "ksu_handle_execveat / do_execveat_common"),
    ("fs/open.c",
     "SYSCALL_DEFINE3(faccessat, int, dfd, const char __user *, filename, int, mode)",
     "\treturn do_faccessat(",
     FACCESSAT, "ksu_handle_faccessat / sys_faccessat"),
    ("fs/stat.c",
     "SYSCALL_DEFINE4(newfstatat, int, dfd, const char __user *, filename,",
     "\terror = vfs_fstatat(",
     STAT, "ksu_handle_stat / sys_newfstatat"),
    ("kernel/reboot.c",
     "SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,",
     "\t/* We only trust the superuser with rebooting the system. */",
     REBOOT, "ksu_handle_sys_reboot / sys_reboot"),
]


def patch(path, fn_anchor, before, payload, label):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as fh:
        src = fh.read()

    if "ksu_handle_" in src and label.split(" / ")[0] in src:
        print("  already hooked: " + label)
        return True

    i = src.find(fn_anchor)
    if i < 0:
        print("  MISSING function anchor for " + label + " in " + path, file=sys.stderr)
        return False

    j = src.find(before, i)
    if j < 0:
        print("  MISSING insertion point for " + label + " in " + path, file=sys.stderr)
        return False

    # insert at the start of the line containing the insertion anchor
    ls = src.rfind("\n", 0, j) + 1
    src = src[:ls] + payload + src[ls:]

    with open(path, "w", encoding="utf-8", errors="surrogateescape") as fh:
        fh.write(src)
    print("  hooked: " + label)
    return True


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    ok = True
    print("installing SukiSU builtin manual hooks under " + root)
    for path, fn_anchor, before, payload, label in JOBS:
        if not patch(root.rstrip("/") + "/" + path, fn_anchor, before, payload, label):
            ok = False
    if not ok:
        print("FATAL: kernel tree lacks expected 5.10 functions; manual hooks NOT complete",
              file=sys.stderr)
        sys.exit(1)
    print("all manual hooks present")


if __name__ == "__main__":
    main()
