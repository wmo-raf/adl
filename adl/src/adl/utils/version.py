# This file is heavily inspired by django.utils.version


def get_version(version):
    """Return a PEP 440-compliant version number from VERSION."""
    version = get_complete_version(version)
    
    # Now build the two parts of the version number:
    # main = X.Y[.Z]
    # sub = .devN - for pre-alpha releases
    #     | {a|b|rc}N - for alpha, beta, and rc releases
    
    main = get_main_version(version)
    
    sub = ""
    if version[3] != "final":
        mapping = {"alpha": "a", "beta": "b", "rc": "rc", "dev": ".dev"}
        sub = mapping[version[3]] + str(version[4])
    
    return main + sub


def get_main_version(version=None, include_patch=True):
    """Return main version (X.Y[.Z]) from VERSION."""
    version = get_complete_version(version)
    if include_patch:
        parts = 2 if version[2] == 0 else 3
    else:
        parts = 2
    return ".".join(str(x) for x in version[:parts])


def get_complete_version(version=None):
    """
    Return a tuple of the Wagtail version. If version argument is non-empty,
    check for correctness of the tuple provided.
    """
    if version is None:
        from adl import VERSION as version
    else:
        assert len(version) == 5
        assert version[3] in ("dev", "alpha", "beta", "rc", "final")
    
    return version


def get_semver_version(version):
    "Returns the semver version (X.Y.Z[-(alpha|beta)]) from VERSION"
    main = ".".join(str(x) for x in version[:3])
    
    sub = ""
    if version[3] != "final":
        sub = "-{}.{}".format(*version[3:])
    return main + sub


def get_main_version_from_string(version_str):
    """
    Return the main version (X.Y[.Z]) from a version string.
    """
    version = version_str.split(".")
    version_release = "final"
    
    release_strings_to_check = ["dev", "alpha", "beta", "rc", "final"]
    for release_string in release_strings_to_check:
        if release_string in version_str:
            parts = version_str.split(release_string)
            version = parts[0].split(".")
            version_release = release_string
            break
    
    if len(version) == 2:
        return int(version[0]), int(version[1]), 0, version_release
    return int(version[0]), int(version[1]), int(version[2]), version_release


def check_version_greater_than_current(version):
    """
    Check if the given version is greater than the current version.
    """
    current_version = get_complete_version()
    current_major, current_minor, current_patch, current_release = current_version[:4]
    
    version = get_main_version_from_string(version)
    major, minor, patch, release = version
    
    # only check for final releases
    if release != "final":
        return False
    
    # If the major version is greater than the current major version, return True
    if major > current_major:
        return True
    
    # If the major version is the same, proceed to check the minor version
    if major == current_major:
        # If the minor version is greater than the current minor version, return True
        if minor > current_minor:
            return True
        
        if minor == current_minor:
            
            # If the major and minor versions are the same, check the patch version
            if patch > current_patch:
                return True
            
            if patch == current_patch and current_release != "final":
                return True
    
    return False
