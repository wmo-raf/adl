# major.minor.patch.release.number
# release must be one of alpha, beta, rc, or final
VERSION = (0, 6, 4, "final", 0)


def get_semver_version(version):
    "Returns the semver version (X.Y.Z[-(alpha|beta)]) from VERSION"
    main = ".".join(str(x) for x in version[:3])
    
    sub = ""
    if version[3] != "final":
        sub = "-{}.{}".format(*version[3:])
    return main + sub


__version__ = get_semver_version(VERSION)
